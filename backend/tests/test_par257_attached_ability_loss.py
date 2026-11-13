"""PAR-257: standing Aura ability loss, composed over the same attached host."""
from __future__ import annotations

import json
import sqlite3

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_authored_card
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle

PT_AURAS = {"Duskmourn's Domination": -3, "Fresh Start": -5, "Mystic Subdual": -2}
UNTAP_AURAS = ("Enchanted River's Grasp", "Flood the Engine", "Stop Cold")
GAINS = (*PT_AURAS, *UNTAP_AURAS)
RESIDUE = ("Quantum Reduction", "Tamiyo's Compleation")
# Enough to pay any printed spell/activation in these isolated gameplay cases.
TEST_MANA_PER_COLOR = 20


@pytest.fixture(scope="module")
def real_cards():
    # Read the isolated test cache directly: no schema initialization or refresh.
    names = (*GAINS, *RESIDUE, "Infinite Coursework", "Ray of Frost")
    with sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True) as db:
        placeholders = ",".join("?" for _ in names)
        rows = db.execute(f"SELECT data FROM cards WHERE name IN ({placeholders})", names).fetchall()
    cards = {c.name: c for (data,) in rows if (c := Card.from_dict(json.loads(data)))}
    assert set(cards) == set(names)
    return cards


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.state.current_phase, engine.state.current_step = "precombat_main", "main1"
    for player in engine.state.players:
        player.mana_pool.add_many({color: TEST_MANA_PER_COLOR for color in "WUBRGC"})
    return engine


def _host(engine, name="Host", owner="p2", counters=None):
    card = Card(id=name, name=name, type_line="Creature — Dragon", is_creature=True,
                power=6, toughness=6, oracle_text="Flying\n{1}: You gain 1 life.")
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    obj.counters.update(counters or {})
    return obj


def _cast(engine, card, host):
    aura = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(aura)
    engine.state.player_by_id("p1").hand.append(aura)
    engine.cast_spell(engine.state.player_by_id("p1"), aura, targets=[host])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert aura.zone == Zone.BATTLEFIELD and aura.attached_to == host.instance_id
    return aura


@pytest.mark.parametrize("name", GAINS)
def test_real_cards_are_fully_modeled_and_cast_with_all_their_abilities(real_cards, name):
    card = real_cards[name]
    result = parse_oracle(card)
    assert result.modeled and not result.unclaimed
    assert not is_authored_card(card)  # These gains come from shared parsing.
    engine = _game()
    host = _host(engine, counters={"charge": 3})
    aura = _cast(engine, card, host)
    assert host.loses_all_abilities and not combat.has(host, "flying")
    assert all(ability.affects == "attached_permanent" for ability in aura.static_effects)
    if name in PT_AURAS:
        assert (host.power, host.toughness) == (6 + PT_AURAS[name], 6)
    else:
        assert host.tapped and continuous.has_no_untap_static(engine.state, host)
    assert host.controller_id == ("p1" if name == "Duskmourn's Domination" else "p2")
    assert host.counters == ({} if name == "Enchanted River's Grasp" else {"charge": 3})
    with pytest.raises(ValueError, match="abilit"):
        engine.activate_ability(engine.state.player_by_id(host.controller_id), host, 0)


@pytest.mark.parametrize("subject", ["enchanted creature", "enchanted permanent"])
def test_standalone_attached_ability_loss_is_outside_the_compound_scope(subject):
    assert static_effect_specs(f"{subject} loses all abilities.") is None


@pytest.mark.parametrize("clause, kinds", [
    ("enchanted creature gets -3/-0 and loses all abilities.", ["anthem", "remove_all_abilities"]),
    ("enchanted creature loses all abilities and doesn't untap during its controller's untap step.",
     ["remove_all_abilities", "no_untap"]),
    ("enchanted permanent loses all abilities and doesn't untap during its controller's untap step.",
     ["remove_all_abilities", "no_untap"]),
])
def test_compound_effects_share_the_attached_scope_without_temporary_grants(clause, kinds):
    effects = static_effect_specs(clause)
    assert [effect.type for effect in effects] == kinds
    assert all(effect.params["affects"] == "attached_permanent" for effect in effects)


@pytest.mark.parametrize("clause", [
    "enchanted creature loses all abilities and you draw a card.",
    "enchanted creature loses all abilities until end of turn.",
    "enchanted creature gets -3/-0 and loses all abilities if you control a wizard.",
    "enchanted creature gets -3/-0 and target creature loses all abilities.",
    "enchanted creature loses all abilities and doesn't untap during your untap step.",
    "enchanted creature loses all abilities and doesn't untap during its controller's next untap step.",
    "enchanted creature loses all abilities and doesn't untap during its controller's untap step, then draw a card.",
    "enchanted creature gets -3/-0 and loses all abilities and doesn't untap during its controller's untap step.",
    "creatures you control lose all abilities and don't untap during their controller's untap step.",
])
def test_near_misses_and_unmodeled_tails_remain_fail_closed(clause):
    assert static_effect_specs(clause) is None
    card = Card(id=clause, name="Unmodeled Aura", type_line="Enchantment — Aura",
                oracle_text="Enchant creature\n" + clause)
    assert not parse_oracle(card).modeled


@pytest.mark.parametrize("name", ["Fresh Start", "Mystic Subdual", "Stop Cold"])
def test_flash_is_preserved_and_allows_casting_in_an_opponents_turn(real_cards, name):
    engine = _game()
    engine.state.active_player_index = 1
    host = _host(engine)
    _cast(engine, real_cards[name], host)
    assert host.loses_all_abilities


@pytest.mark.parametrize("name", UNTAP_AURAS)
def test_host_does_not_untap_in_its_controllers_step_but_an_effect_can_untap_it(real_cards, name):
    engine = _game()
    host = _host(engine)
    _cast(engine, real_cards[name], host)
    engine.state.active_player_index = 1
    engine._step_untap()
    assert host.tapped
    engine.rules.set_tapped(host, False)
    assert not host.tapped
    engine.rules.set_tapped(host, True)
    engine._step_untap()
    assert host.tapped


@pytest.mark.parametrize("name", ["Fresh Start", "Stop Cold", "Duskmourn's Domination"])
def test_reattachment_and_aura_departure_restore_the_old_host(real_cards, name):
    engine = _game()
    old_host = _host(engine, "Old Host")
    new_host = _host(engine, "New Host")
    aura = _cast(engine, real_cards[name], old_host)
    assert engine.rules.attach_to_target(aura, new_host, check_control=False)
    engine.recompute_continuous_effects()
    assert not old_host.loses_all_abilities and combat.has(old_host, "flying")
    assert (old_host.power, old_host.toughness) == (6, 6) and old_host.controller_id == "p2"
    assert not continuous.has_no_untap_static(engine.state, old_host)
    assert new_host.loses_all_abilities and not combat.has(new_host, "flying")
    engine.rules.destroy(aura)
    engine.recompute_continuous_effects()
    assert not new_host.loses_all_abilities and combat.has(new_host, "flying")
    assert (new_host.power, new_host.toughness) == (6, 6) and new_host.controller_id == "p2"
    assert not continuous.has_no_untap_static(engine.state, new_host)


def test_ability_removal_does_not_remove_pt_counters_or_replace_base_pt(real_cards):
    engine = _game()
    host = _host(engine, counters={"+1/+1": 2})
    _cast(engine, real_cards["Fresh Start"], host)
    assert host.counters["+1/+1"] == 2
    assert (host.power, host.toughness) == (3, 8)  # 6/6 base + two counters -5/-0.


@pytest.mark.parametrize("name, residual", [
    ("Quantum Reduction", "teamwork"), ("Tamiyo's Compleation", "unattach"),
])
def test_additionally_blocked_cards_keep_their_independent_gaps(real_cards, name, residual):
    result = parse_oracle(real_cards[name])
    assert not result.modeled
    assert any(residual in clause for clause in result.unclaimed)
    assert not any("loses all abilities" in clause for clause in result.unclaimed)


def test_infinite_coursework_keeps_its_authored_definition(real_cards):
    assert is_authored_card(real_cards["Infinite Coursework"])


def test_ray_of_frost_remains_unmodeled_on_its_standalone_conditional_loss(real_cards):
    card = real_cards["Ray of Frost"]
    result = parse_oracle(card)
    assert not result.modeled and not is_authored_card(card)
    assert result.unclaimed == ["as long as enchanted creature is red, it loses all abilities."]
