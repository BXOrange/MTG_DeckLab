"""MEC-137 -- Living metal (RULE 702.161a) and the Transformers back faces (the converted side of MEC-136)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.phases import default_turn_sequence
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

ARCEE = "Arcee, Sharpshooter // Arcee, Acrobatic Coupe"
CYCLONUS = "Cyclonus, the Saboteur // Cyclonus, Cybertronian Fighter"
GOLDBUG = "Goldbug, Humanity's Ally // Goldbug, Scrappy Scout"
STARSCREAM = "Starscream, Power Hungry // Starscream, Seeker Leader"
ULTRA_MAGNUS = "Ultra Magnus, Tactician // Ultra Magnus, Armored Carrier"
FIVE = (ARCEE, CYCLONUS, GOLDBUG, STARSCREAM, ULTRA_MAGNUS)


def cached(name):
    try:
        with sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT data FROM cards WHERE name = ?", (name,)).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        pytest.skip(f"{name} is not in the card cache")
    return Card.from_dict(json.loads(row[0]))


def synthetic_vehicle(oracle="Living metal"):
    return Card(
        id="lm", name="Metal Front // Metal Back", type_line="Artifact Creature — Robot", is_creature=True,
        layout="transform", mana_cost_string="{2}", converted_mana_cost=2, power=1, toughness=1,
        oracle_text="Flying", back_name="Metal Back", back_type_line="Artifact — Vehicle", back_oracle_text=oracle,
        back_power=4, back_toughness=5, back_keywords=["Living metal"],
    )


def new_engine():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.active_player


def converted_permanent(engine, player, card):
    """The permanent on the battlefield with its back face up (as after a MEC-136 converted cast)."""
    obj = GameObject(card, owner_id=player.id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player.id
    engine.state.battlefield.append(obj)
    bind_from_catalogue(obj)
    assert engine.rules.transform_permanent(obj)
    engine.recompute_continuous_effects()
    return obj


def opponent_of(engine, player):
    return next(p for p in engine.state.players if p.id != player.id)


def set_active(engine, player):
    engine.state.active_player_index = engine.state.players.index(player)
    engine.recompute_continuous_effects()


# --- Living metal itself -----------------------------------------------------------------------------------

def test_living_metal_is_an_artifact_creature_only_on_its_controllers_turn():
    engine, player = new_engine()
    obj = converted_permanent(engine, player, synthetic_vehicle())
    # RULE 702.161a: during your turn the Vehicle is an artifact creature (with its printed Vehicle P/T).
    assert obj.is_creature and {"artifact", "creature"} <= obj.type_words
    assert (obj.power, obj.toughness) == (4, 5)
    set_active(engine, opponent_of(engine, player))
    assert not obj.is_creature and "creature" not in obj.type_words and "artifact" in obj.type_words
    set_active(engine, player)
    assert obj.is_creature


def test_living_metal_keeps_its_other_types_and_survives_state_based_actions():
    engine, player = new_engine()
    obj = converted_permanent(engine, player, synthetic_vehicle())
    engine.rules.check_state_based_actions()
    assert obj in engine.state.battlefield  # a 0/0 would die to RULE 704.5f
    assert obj.has_subtype("Vehicle")


def test_every_living_metal_card_carries_the_static():
    for name in ("Optimus Prime, Hero // Optimus Prime, Autobot Leader", "Megatron, Tyrant // Megatron, Destructive Force",
                 "Jetfire, Ingenious Scientist // Jetfire, Air Guardian", "Prowl, Stoic Strategist // Prowl, Pursuit Vehicle"):
        engine, player = new_engine()
        obj = converted_permanent(engine, player, cached(name))
        assert obj.is_creature, name
        assert any(getattr(e, "layer", None) == "type" for e in obj.static_effects), name
        set_active(engine, opponent_of(engine, player))
        assert not obj.is_creature, name


# --- the five back faces --------------------------------------------------------------------------------

def back_face_of(name):
    return cached(name).back_face()


@pytest.mark.parametrize("name", FIVE)
def test_back_face_is_modeled(name):
    back = back_face_of(name)
    result = parse_oracle(back) if name == GOLDBUG else None
    if result is not None:
        assert result.modeled, result.unclaimed
    # Hand-authored back faces are registered; either way the bound face has abilities beyond Living metal.
    engine, player = new_engine()
    obj = converted_permanent(engine, player, cached(name))
    assert obj.triggered_abilities, name
    assert any(getattr(e, "layer", None) == "type" for e in obj.static_effects)


def fire_combat_damage_to_player(engine, obj, victim):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(
        EventType.DAMAGE, source_id=obj.instance_id, instance_id=obj.instance_id, target_id=victim.id, amount=2,
        combat=True, is_player=True, controller_id=obj.controller_id, player_id=victim.id,
    ))
    engine.resolve_until_stable()


def test_starscream_makes_the_damaged_player_the_monarch_only_when_nobody_is(  ):
    engine, player = new_engine()
    obj = converted_permanent(engine, player, cached(STARSCREAM))
    victim = opponent_of(engine, player)
    assert engine.state.monarch_id is None
    fire_combat_damage_to_player(engine, obj, victim)
    assert engine.state.monarch_id == victim.id
    # "if there is no monarch": a second hit while someone holds it does nothing.
    engine.state.monarch_id = player.id
    fire_combat_damage_to_player(engine, obj, victim)
    assert engine.state.monarch_id == player.id


def test_starscream_converts_when_its_controller_becomes_the_monarch():
    engine, player = new_engine()
    obj = converted_permanent(engine, player, cached(STARSCREAM))
    assert obj.transformed
    engine.rules.become_monarch(player)
    engine.resolve_until_stable()
    assert not obj.transformed and obj.name.startswith("Starscream, Power Hungry")


def test_goldbug_human_spells_cannot_be_countered_and_other_spells_can():
    engine, player = new_engine()
    converted_permanent(engine, player, cached(GOLDBUG))
    human = GameObject(Card(id="h", name="Human Guy", type_line="Creature — Human Soldier", is_creature=True,
                            power=1, toughness=1), owner_id=player.id, zone=Zone.STACK)
    other = GameObject(Card(id="g", name="Goblin Guy", type_line="Creature — Goblin", is_creature=True,
                            power=1, toughness=1), owner_id=player.id, zone=Zone.STACK)
    for obj in (human, other):
        obj.controller_id = player.id
    assert engine.rules._is_cant_be_countered(human)
    assert not engine.rules._is_cant_be_countered(other)
    opp_human = GameObject(human.card, owner_id=opponent_of(engine, player).id, zone=Zone.STACK)
    opp_human.controller_id = opponent_of(engine, player).id
    assert not engine.rules._is_cant_be_countered(opp_human)  # "Human spells *you* control"


def vanilla(engine, player, name="Bear", subtype="Bear", power=2, toughness=2):
    obj = GameObject(Card(id=name, name=name, type_line=f"Creature — {subtype}", is_creature=True,
                          power=power, toughness=toughness), owner_id=player.id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player.id
    obj.summoning_sick = False
    engine.state.battlefield.append(obj)
    bind_from_catalogue(obj)
    return obj


def attack_with(engine, player, *attackers):
    engine.state.current_phase = "combat"
    engine.state.current_step = "declare_attackers"
    defender = opponent_of(engine, player)
    for attacker in attackers:
        attacker.summoning_sick = False
    engine.declare_attackers(player, [{"attacker": a, "defender": defender} for a in attackers])
    engine._fire_player_attacked_events()  # RULE 508.1: the declaration-level events ("~ and a Human attack")
    engine.resolve_until_stable()


def test_goldbug_draws_and_converts_when_it_attacks_with_a_human():
    engine, player = new_engine()
    goldbug = converted_permanent(engine, player, cached(GOLDBUG))
    human = vanilla(engine, player, "Human Guy", "Human Soldier")
    engine.recompute_continuous_effects()
    player.library.append(vanilla(engine, player, "Library Card"))
    engine.state.battlefield.pop()  # the library copy is not on the battlefield
    before = len(player.hand)
    attack_with(engine, player, goldbug, human)
    assert len(player.hand) == before + 1
    assert not goldbug.transformed  # converted back to the Robot front


def test_goldbug_does_nothing_when_no_human_attacks_with_it():
    engine, player = new_engine()
    goldbug = converted_permanent(engine, player, cached(GOLDBUG))
    bear = vanilla(engine, player)
    engine.recompute_continuous_effects()
    before = len(player.hand)
    attack_with(engine, player, goldbug, bear)
    assert len(player.hand) == before and goldbug.transformed


def test_ultra_magnus_gives_indestructible_and_converts_only_at_total_power_eight():
    for extra_power, converts in ((3, False), (4, True)):
        engine, player = new_engine()
        magnus = converted_permanent(engine, player, cached(ULTRA_MAGNUS))  # 4 power while a creature
        ally = vanilla(engine, player, "Ally", "Bear", extra_power, 2)
        engine.recompute_continuous_effects()
        attack_with(engine, player, magnus, ally)
        assert combat.has(ally, "indestructible")
        assert (not magnus.transformed) is converts, extra_power


def test_arcee_counts_each_targeted_creature_or_vehicle_you_control():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = new_engine()
    arcee = converted_permanent(engine, player, cached(ARCEE))
    bear = vanilla(engine, player)
    foe = vanilla(engine, opponent_of(engine, player), "Foe")
    engine.state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id=player.id, controller_id=player.id, instance_id="spell-1",
        target_instance_ids=[bear.instance_id, foe.instance_id, arcee.instance_id],
    ))
    engine.resolve_until_stable()
    # Bear and Arcee itself (a Vehicle you control) count; the opponent's creature does not.
    assert not arcee.transformed
    assert arcee.counters.get("+1/+1") == 2


def test_arcee_ignores_a_spell_that_targets_only_opposing_creatures():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = new_engine()
    arcee = converted_permanent(engine, player, cached(ARCEE))
    foe = vanilla(engine, opponent_of(engine, player), "Foe")
    engine.state.fire_event(GameEvent(
        EventType.SPELL_CAST, player_id=player.id, controller_id=player.id, instance_id="spell-2",
        target_instance_ids=[foe.instance_id],
    ))
    engine.resolve_until_stable()
    assert arcee.transformed and not arcee.counters.get("+1/+1")


def test_cyclonus_converts_and_adds_a_beginning_phase_after_combat():
    engine, player = new_engine()
    cyclonus = converted_permanent(engine, player, cached(CYCLONUS))
    engine._turn_steps = list(default_turn_sequence().iter_steps())
    engine._cursor = next(i for i, (_, s) in enumerate(engine._turn_steps) if s.name == "combat_damage") + 1
    engine.state.current_phase, engine.state.current_step = "combat", "combat_damage"
    victim = opponent_of(engine, player)
    fire_combat_damage_to_player(engine, cyclonus, victim)
    assert not cyclonus.transformed
    assert engine.state.pending_extra_beginning_phases == 1
    engine._insert_pending_beginning_phases()
    names = [s.name for _, s in engine._turn_steps[engine._cursor:]]
    # RULE 500.8: directly after the combat phase, before the postcombat main phase.
    assert names[:5] == ["end_combat", "untap", "upkeep", "draw", "main2"]
