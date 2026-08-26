"""cEDH staples cube — batch 24: the board-wide ability-strip primitive
(layer 6, RULE 613.7f).

New core capability: a `remove_all_abilities` static ability sets
`GameObject.loses_all_abilities` on every affected creature during
`continuous.recompute`. That strips *all* keywords (`combat._obj_keywords`
returns empty) and stops its triggered abilities firing (`_collect_triggers`
skips it) and its activated abilities being activated (`can_activate` returns
False) — a whole-ability removal, not just a named keyword like the existing
`remove_keyword`.

Registers Humility (ability strip + a layer-7b `pt_set` to base 1/1). Dress
Down reuses the same static but adds an ETB draw + an end-step self-sacrifice
and stays deferred.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec


def _engine() -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _humility(eng, controller="p1") -> GameObject:
    card = Card(id="hum", name="Humility", type_line="Enchantment",
                oracle_text="All creatures lose all abilities and have base "
                            "power and toughness 1/1.")
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _flyer(eng, owner="p2", power=5, toughness=5) -> GameObject:
    card = Card(id="fly", name="Serra Angel", type_line="Creature — Angel",
                is_creature=True, power=power, toughness=toughness,
                keywords=["Flying"])
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.intrinsic_keywords = {"flying"}
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# 1. The ability-strip static
# ---------------------------------------------------------------------------


def test_humility_strips_keywords_and_sets_base_1_1():
    eng = _engine()
    flyer = _flyer(eng, power=5, toughness=5)
    assert combat.has_flying(flyer)
    _humility(eng)
    continuous.recompute(eng.state)

    assert flyer.loses_all_abilities
    assert not combat.has_flying(flyer), "Humility strips flying"
    assert (flyer.power, flyer.toughness) == (1, 1), "base P/T set to 1/1"


def test_without_humility_the_flyer_keeps_its_abilities():
    eng = _engine()
    flyer = _flyer(eng)
    continuous.recompute(eng.state)
    assert not flyer.loses_all_abilities
    assert combat.has_flying(flyer)


def test_ability_strip_suppresses_triggered_abilities():
    eng = _engine()
    # A creature with an ETB trigger that would draw a card.
    card = Card(id="trg", name="Trigger Bear", type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ability = bind_ability(
        AbilitySpec("triggered", [EffectSpec("draw", {"count": 1})],
                    trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}}),
        obj,
    )
    obj.triggered_abilities.append(ability)
    eng.state.add_to_battlefield(obj)

    _humility(eng)
    continuous.recompute(eng.state)
    assert obj.loses_all_abilities

    # Firing its trigger event now collects nothing.
    from mtg_analyzer.models.events import GameEvent
    eng.rules.pending_triggers.clear()
    eng.state.fire_event(GameEvent(EventType.ATTACKS, player_id="p1",
                                   instance_id=obj.instance_id,
                                   object_types=sorted(obj.type_words)))
    assert eng.rules.pending_triggers == [], "stripped creature's trigger doesn't fire"


def test_ability_strip_clears_when_humility_leaves():
    eng = _engine()
    flyer = _flyer(eng)
    hum = _humility(eng)
    continuous.recompute(eng.state)
    assert flyer.loses_all_abilities

    eng.state.battlefield.remove(hum)
    continuous.recompute(eng.state)
    assert not flyer.loses_all_abilities, "the strip is re-derived, so it lifts"
    assert combat.has_flying(flyer)


# ---------------------------------------------------------------------------
# 2. Registration
# ---------------------------------------------------------------------------


def test_humility_registered_with_two_statics():
    assert "humility" in ac._REGISTRY
    specs = ac._REGISTRY["humility"]()
    types = {e.type for s in specs for e in s.effects}
    assert "remove_all_abilities" in types
    assert "pt_set" in types
