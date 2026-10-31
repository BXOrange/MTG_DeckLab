"""Defined X bonuses share attached anthems and resolve-time pumps."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause


STATIC = [
    ("Bonehoard", "+X/+X", "the number of creature cards in all graveyards"),
    ("Chainsaw", "+X/+0", "the number of rev counters on Chainsaw"),
    ("Cranial Ram", "+X/+1", "the number of artifacts you control"),
    ("Hedron Matrix", "+X/+X", "its mana value"),
    ("Opaline Bracers", "+X/+X", "the number of charge counters on Opaline Bracers"),
    ("Staff of Titania", "+X/+X", "the number of Forests you control"),
]
BRONZE = "{2}: Until end of turn, equipped creature gets +X/+0, where X is the number of times this ability has resolved this turn.\nEquip {1}"


def engine_and_host():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0)
    engine.begin_turn()
    host = add(engine.state, "Host", "Creature", power=2, toughness=3, is_creature=True, mana_cost_string="{3}{G}", converted_mana_cost=4)
    return engine, host


def add(state, name, type_line, pid="p1", zone=Zone.BATTLEFIELD, **kwargs):
    obj = GameObject(Card(id=name, name=name, type_line=type_line, **kwargs), owner_id=pid, zone=zone)
    obj.controller_id = pid
    if zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    else:
        state.player_by_id(pid).graveyard.append(obj)
    return obj


@pytest.mark.parametrize("name,bonus,quantity", STATIC)
def test_real_equipment_parses_and_executes(name, bonus, quantity):
    engine, host = engine_and_host()
    source = add(engine.state, name, "Artifact — Equipment", oracle_text=f"Equipped creature gets {bonus}, where X is {quantity}.\nEquip {{2}}")
    assert parse_oracle(source.card).modeled
    bind_from_catalogue(source)
    source.attached_to = host.instance_id
    source.counters.update({"rev": 5, "charge": 6})
    host.counters.update({"rev": 11, "charge": 12})
    add(engine.state, "Forest", "Basic Land — Forest")
    add(engine.state, "Other Forest", "Basic Land — Forest", pid="p2")
    add(engine.state, "Dead A", "Creature", zone=Zone.GRAVEYARD, is_creature=True)
    add(engine.state, "Dead B", "Creature", pid="p2", zone=Zone.GRAVEYARD, is_creature=True)
    add(engine.state, "Dead Land", "Land", zone=Zone.GRAVEYARD)
    host.controller_id = "p2"  # Counts still belong to the Equipment controller.
    engine.recompute_continuous_effects()
    x = {"Bonehoard": 2, "Chainsaw": 5, "Cranial Ram": 1, "Hedron Matrix": 4, "Opaline Bracers": 6, "Staff of Titania": 1}[name]
    t = x if bonus.endswith("+X") else int(bonus[-1])
    assert (host.power, host.toughness) == (2 + x, 3 + t)
    if name == "Bonehoard":
        add(engine.state, "Dead C", "Creature", zone=Zone.GRAVEYARD, is_creature=True)
        x += 1
    elif name in ("Chainsaw", "Opaline Bracers"):
        source.counters["rev" if name == "Chainsaw" else "charge"] += 1
        x += 1
    elif name == "Cranial Ram":
        add(engine.state, "Another artifact", "Artifact")
        x += 1
    elif name == "Staff of Titania":
        add(engine.state, "Another Forest", "Land — Forest")
        x += 1
    else:
        host.card.converted_mana_cost = 5
        x = 5
    engine.recompute_continuous_effects()
    t = x if bonus.endswith("+X") else int(bonus[-1])
    assert (host.power, host.toughness) == (2 + x, 3 + t)
    source.attached_to = None
    engine.recompute_continuous_effects()
    assert (host.power, host.toughness) == (2, 3)


@pytest.mark.parametrize("clause", [
    "equipped creature gets +x/+x, where x is its intensity",
    "equipped creature gets +x/+x, where x is twice the number of charge counters on it",
    "equipped creature gets +x/+x, where x is the number of charge counters on it plus the number of charge counters on ~",
    "equipped creature gets +x/+y, where x is the first chosen result and y is the second",
    "equipped creature gets +x/+x, where x is the number of artifacts you control and draw a card",
    "equipped creature gets +x/+x, where x is its power",
    "equipped creature gets +x/+x, where x is the number of artifacts you control until end of turn",
])
def test_unknown_or_nonstatic_quantity_fails_closed(clause):
    assert static_effect_specs(clause) is None


def test_source_and_host_counter_selectors_are_distinct():
    source = static_effect_specs("equipped creature gets +x/+x, where x is the number of charge counters on ~")[0]
    host = static_effect_specs("equipped creature gets +x/+x, where x is the number of charge counters on it")[0]
    assert source.params["power_count"] == {"counters_on": "source", "kind": "charge"}
    assert host.params["power_count"] == {"counters_on": "affected", "kind": "charge"}


def test_bronze_counts_resolutions_and_reads_current_attachment():
    engine, host = engine_and_host()
    source = add(engine.state, "Bronze Cudgels", "Artifact — Equipment", oracle_text=BRONZE)
    assert parse_oracle(source.card).modeled
    bind_from_catalogue(source)
    source.attached_to = host.instance_id
    player = engine.state.player_by_id("p1")
    player.mana_pool.add("C", 6)
    engine.activate_ability(player, source, 0)
    engine.activate_ability(player, source, 0)
    engine.rules.resolve_top_of_stack()
    assert host.power == 3
    replacement = add(engine.state, "New host", "Creature", is_creature=True, power=1, toughness=3)
    source.attached_to = replacement.instance_id
    engine.rules.resolve_top_of_stack()
    assert host.power == 3
    assert replacement.power == 3
    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert host.power == 2
    assert replacement.power == 1
    engine.begin_turn()  # RULE 500.1: a real new turn resets the per-turn count
    source.attached_to = replacement.instance_id
    player.mana_pool.add("C", 2)
    engine.activate_ability(player, source, 0)
    engine.rules.resolve_top_of_stack()
    assert source.ability_resolutions[next(iter(source.ability_resolutions))] == (engine.state.internal_turn.number, 1)
    assert replacement.power == 2


def test_bronze_does_not_claim_activation_count_or_extra_instruction():
    body = BRONZE.split(": ", 1)[1].split(".\n", 1)[0].lower()
    assert match_clause(body.replace("resolved", "been activated")) is None
    assert match_clause(body + " and draw a card") is None


def test_host_counter_quantity_executes_and_updates():
    engine, host = engine_and_host()
    source = add(engine.state, "Counter Equipment", "Artifact — Equipment", oracle_text="Equipped creature gets +X/+X, where X is the number of charge counters on it.")
    bind_from_catalogue(source)
    source.attached_to = host.instance_id
    source.counters["charge"] = 9
    host.counters["charge"] = 2
    engine.recompute_continuous_effects()
    assert (host.power, host.toughness) == (4, 5)
    host.counters["charge"] = 0
    engine.recompute_continuous_effects()
    assert (host.power, host.toughness) == (2, 3)


@pytest.mark.parametrize("name,where", [("Exoskeletal Armor", "all graveyards"), ("Wreath of Geists", "your graveyard")])
def test_aura_shared_shape_counts_source_controller_graveyard(name, where):
    engine, host = engine_and_host()
    source = add(engine.state, name, "Enchantment — Aura", oracle_text=f"Enchant creature\nEnchanted creature gets +X/+X, where X is the number of creature cards in {where}.")
    assert parse_oracle(source.card).modeled
    bind_from_catalogue(source)
    source.attached_to = host.instance_id
    host.controller_id = "p2"
    add(engine.state, "Dead One", "Creature", zone=Zone.GRAVEYARD, is_creature=True)
    add(engine.state, "Dead Two", "Creature", pid="p2", zone=Zone.GRAVEYARD, is_creature=True)
    engine.recompute_continuous_effects()
    x = 2 if where == "all graveyards" else 1
    assert (host.power, host.toughness) == (2 + x, 3 + x)
