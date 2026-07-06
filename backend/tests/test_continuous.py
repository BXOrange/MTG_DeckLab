"""Tests for the continuous-effects layer engine (game/continuous.py, RULE 613)."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effects import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine


def creature(name="Bear", power=2, toughness=2, controller="p1", **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        is_creature=True, power=power, toughness=toughness, **kw,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [creature()]), ("p2", "Bob", [creature()])],
        starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def static(layer, affects, params, source):
    ab = StaticAbility(layer, affects=affects, params=params, source=source)
    source.static_effects.append(ab)
    return ab


# -- Layer 7: power/toughness ------------------------------------------------


def test_anthem_pumps_other_creatures_you_control():
    eng = make_engine()
    lord = put(eng.state, creature("Lord", power=2, toughness=2))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    enemy = put(eng.state, creature("Enemy", power=2, toughness=2), controller="p2")
    static("pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1}, lord)
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (3, 3)   # pumped
    assert (lord.power, lord.toughness) == (2, 2)   # "other" excludes itself
    assert (enemy.power, enemy.toughness) == (2, 2)  # not yours


def test_anthem_stacks_with_counters_in_layer_order():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 2)
    static("pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1}, lord)
    continuous.recompute(eng.state)
    # base 2/2 + 2 counters (7c) + 1/1 anthem (7d) = 5/5.
    assert (bear.power, bear.toughness) == (5, 5)


def test_pt_set_applies_before_counters():
    eng = make_engine()
    src = put(eng.state, creature("Humility"))
    bear = put(eng.state, creature("Bear", power=5, toughness=5))
    bear.add_counters("+1/+1", 1)
    static("pt_set", "all_creatures", {"power": 1, "toughness": 1}, src)
    continuous.recompute(eng.state)
    # 7b set to 1/1, then 7c +1 counter → 2/2 (set wipes the printed 5/5).
    assert (bear.power, bear.toughness) == (2, 2)


# -- Layer 6: ability granting flows into combat -----------------------------


def test_granted_flying_flows_into_combat():
    eng = make_engine()
    lord = put(eng.state, creature("Wind Lord"))
    bear = put(eng.state, creature("Bear"))
    assert not combat.has_flying(bear)
    static("ability", "creatures_you_control", {"keywords": ["flying"]}, lord)
    continuous.recompute(eng.state)
    assert combat.has_flying(bear)  # anthem-granted flying is real in combat
    assert "Flying" in bear.to_dict()["keywords"]


# -- Layer 4: type change ----------------------------------------------------


def test_type_change_animates_a_land_into_a_creature():
    eng = make_engine()
    land = put(eng.state, Card(id="Mishra", name="Mishra's Factory",
                               type_line="Land", is_land=True))
    assert not land.is_creature
    static("type", "self", {"add_types": ["creature"], "power": 2, "toughness": 2}, land)
    continuous.recompute(eng.state)
    assert land.is_creature
    assert (land.power, land.toughness) == (2, 2)
    assert land.to_dict()["is_creature"] is True


# -- Trace -------------------------------------------------------------------


def test_static_trace_records_each_layer():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 1)
    static("ability", "creatures_you_control", {"keywords": ["flying"]}, lord)
    static("pt_mod", "other_creatures_you_control", {"power": 2, "toughness": 0}, lord)
    continuous.recompute(eng.state)
    layers = [entry["layer"] for entry in bear.static_trace]
    assert 6 in layers and 7 in layers          # keyword grant + P/T changes
    # Final P/T reflects the whole trace: 2/2 +1 counter +2/+0 = 5/3.
    assert (bear.power, bear.toughness) == (5, 3)


# -- Cost reduction (RULE 601.2f) --------------------------------------------


def test_cost_reduction_lowers_generic_only():
    eng = make_engine()
    p1 = eng.state.active_player
    reducer = put(eng.state, creature("Rock"))
    static("cost", "your_spells", {"generic": 2}, reducer)
    spell = Card(id="Big", name="Big Spell", type_line="Sorcery",
                 mana_cost_string="{3}{G}", converted_mana_cost=4, is_sorcery=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    cost = eng.effective_cast_cost(p1, obj)
    assert cost.converted_mana_cost == 2          # {3}{G} → {1}{G}
    assert cost.color_identity == {"G"}           # colour pip untouched


def test_cost_increase_raises_generic():
    eng = make_engine()
    p1 = eng.state.active_player
    tax = put(eng.state, creature("Tax"))
    static("cost", "your_spells", {"generic": 1, "increase": True}, tax)
    spell = Card(id="S", name="S", type_line="Sorcery", mana_cost_string="{1}{R}",
                 converted_mana_cost=2, is_sorcery=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    assert eng.effective_cast_cost(p1, obj).converted_mana_cost == 3  # {1}{R} → {2}{R}


# -- Binding a static ability from a spec ------------------------------------


def test_bind_and_attach_static_ability():
    from mtg_analyzer.game.effect_binder import attach_to_object
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    eng = make_engine()
    lord = put(eng.state, Card(id="Lord", name="Anthem", type_line="Enchantment"))
    bear = put(eng.state, creature("Bear", power=1, toughness=1))
    attach_to_object(
        lord,
        [AbilitySpec("static", [EffectSpec("anthem", {"power": 2, "toughness": 2,
                     "affects": "creatures_you_control"})], raw_text="+2/+2")],
    )
    assert lord.static_effects  # bound and attached, not refused
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (3, 3)
