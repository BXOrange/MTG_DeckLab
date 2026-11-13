"""Shuriken's real equip, tap/unattach cost, damage source and control change."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import activate, card, filler, game, main_phase


def _board(subtype="Warrior"):
    engine = game()
    equipment = card(engine, "Shuriken")
    host = filler(engine, "Host", type_line=f"Creature — {subtype}", power=2, toughness=2)
    victim = filler(engine, "Victim", player="p2", power=3, toughness=3)
    player = engine.state.player_by_id("p1")
    player.mana_pool.add("C", 2)
    activate(engine, equipment, targets=[host])
    assert equipment.attached_to == host.instance_id
    return engine, player, equipment, host, victim


def _throw(engine, player, host, victim):
    main_phase(engine)
    engine.activate_ability(player, host, targets=[victim])


@pytest.mark.parametrize("subtype,recipient", [("Warrior", "p2"), ("Ninja", "p1")])
def test_equipped_creature_pays_cost_and_shuriken_deals_damage_then_changes_control(subtype, recipient):
    engine, player, equipment, host, victim = _board(subtype)
    a, b = specs_for(equipment.card), specs_for(equipment.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(host.granted_activated_abilities) == 1
    _throw(engine, player, host, victim)
    assert host.tapped and equipment.attached_to is None
    assert victim.damage_marked == 0  # unattach is paid before resolution
    assert not equipment.tapped
    engine.resolve_until_stable()
    assert victim.damage_marked == 2 and equipment.controller_id == recipient
    hits = [event for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE]
    assert len(hits) == 1 and hits[0].get("source_id") == equipment.instance_id
    assert not host.granted_activated_abilities


@pytest.mark.parametrize("before,after,recipient", [("Ninja", "Warrior", "p1"), ("Warrior", "Ninja", "p2")])
def test_ninja_check_uses_the_type_when_unattached_not_the_type_at_resolution(before, after, recipient):
    engine, player, equipment, host, victim = _board(before)
    _throw(engine, player, host, victim)
    host.card.type_line = f"Creature — {after}"
    engine.resolve_until_stable()
    assert equipment.controller_id == recipient


def test_summoning_sickness_prevents_tap_activation_and_keeps_equipment_attached():
    engine, player, equipment, host, victim = _board()
    host.summoning_sick = True
    with pytest.raises(ValueError):
        _throw(engine, player, host, victim)
    assert equipment.attached_to == host.instance_id and not host.tapped


def test_illegal_target_prevents_damage_and_control_change():
    engine, player, equipment, host, victim = _board()
    _throw(engine, player, host, victim)
    engine.rules.exile(victim)
    engine.resolve_until_stable()
    assert equipment.controller_id == "p1" and victim.damage_marked == 0


def test_lethal_damage_still_hands_equipment_to_targets_controller():
    engine, player, equipment, host, victim = _board()
    victim.card.toughness = 2
    _throw(engine, player, host, victim)
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD and equipment.controller_id == "p2"


def test_clone_preserves_paid_cost_and_grantor():
    engine, player, equipment, host, victim = _board("Ninja")
    _throw(engine, player, host, victim)
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(victim.instance_id).damage_marked == 2
    assert clone.state.find_object(equipment.instance_id).controller_id == "p1"
    assert victim.damage_marked == 0


def test_overlapping_activations_keep_independent_unattachment_history():
    engine, player, equipment, host, victim = _board("Warrior")
    _throw(engine, player, host, victim)
    ninja = filler(engine, "Ninja", type_line="Creature — Ninja", power=2, toughness=2)
    second = filler(engine, "Second victim", player="p2", power=3, toughness=3)
    # An attachment effect can reattach the Equipment while the first ability waits.
    assert engine.rules.attach_to_target(equipment, ninja)
    engine.recompute_continuous_effects()
    _throw(engine, player, ninja, second)
    engine.rules.resolve_top_of_stack()
    assert second.damage_marked == 2 and equipment.controller_id == "p1"
    engine.resolve_until_stable()
    assert victim.damage_marked == 2 and equipment.controller_id == "p2"


def test_changeling_counts_as_ninja_at_payment():
    engine, player, equipment, host, victim = _board("Shapeshifter")
    host.intrinsic_keywords.add("changeling")
    engine.recompute_continuous_effects()
    _throw(engine, player, host, victim)
    engine.resolve_until_stable()
    assert victim.damage_marked == 2 and equipment.controller_id == "p1"
