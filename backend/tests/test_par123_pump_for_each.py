"""PAR-123: "gets +N/+M until end of turn for each `<quantity>`" as a ``bind`` over a ``pump``.

The amount path used to accept only a single ``amount``/``count`` magnitude, so a pump
that scales per counted object ("~ gets +1/+0 for each other attacking creature") had
nowhere to put the measured number. Each nonzero printed half of the pump now takes it.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0)
    return engine, engine.state


def _creature(state, name, owner="p1", subtype="Bear", power=2, toughness=2, attacking=False):
    obj = GameObject(Card(id=name, name=name, type_line=f"Creature — {subtype}", is_creature=True,
                          power=power, toughness=toughness), owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.attacking = attacking
    state.add_to_battlefield(obj)
    return obj


def _run(engine, clause, source, **flags):
    [spec] = parse_effect_body(clause, **flags)
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context)
    engine.resolve_until_stable()


@pytest.mark.parametrize("clause, halves, multiply", [
    ("~ gets +1/+0 until end of turn for each other attacking creature", {"power": "$n", "toughness": 0}, None),
    ("~ gets +1/+1 until end of turn for each elf you control", {"power": "$n", "toughness": "$n"}, None),
    ("~ gets +2/+2 until end of turn for each elf you control", {"power": "$n", "toughness": "$n"}, 2),
])
def test_a_pump_scales_per_counted_object(clause, halves, multiply):
    [spec] = parse_effect_body(clause)
    assert spec.type == "bind"
    [effect] = spec.params["effects"]
    assert effect["type"] == "pump" and effect["params"] == halves
    assert spec.params["amount"].get("multiply") == multiply


@pytest.mark.parametrize("clause", [
    "~ gets +2/+1 until end of turn for each elf you control",   # two different halves
    "~ gets -1/-1 until end of turn for each elf you control",   # negative halves
])
def test_a_pump_with_no_single_unit_is_refused(clause):
    assert parse_effect_body(clause) is None


def test_other_attacking_creatures_are_counted_without_the_source():
    engine, state = _engine()
    me = _creature(state, "me", attacking=True)
    _creature(state, "a", attacking=True)
    _creature(state, "b", attacking=True)
    _creature(state, "idle")
    _run(engine, "~ gets +1/+0 until end of turn for each other attacking creature", me)
    assert (me.power, me.toughness) == (4, 2)


def test_a_multiplied_pump_scales_both_halves():
    engine, state = _engine()
    me = _creature(state, "me", subtype="Elf")
    _creature(state, "e1", subtype="Elf")
    _creature(state, "human", subtype="Human")
    _run(engine, "~ gets +2/+2 until end of turn for each elf you control", me)
    assert (me.power, me.toughness) == (6, 6)     # two elves → +4/+4


def test_other_under_a_group_trigger_is_refused():
    """"other" counts against the ability's source, not the firing creature."""
    assert parse_effect_body(
        "it gets +1/+1 until end of turn for each other creature you control", group_subject=True) is None
    assert parse_effect_body(
        "it gets +1/+1 until end of turn for each creature you control", group_subject=True) is not None


@pytest.mark.parametrize("name, oracle", [
    ("Goblin Piledriver", "Protection from blue\nWhenever this creature attacks, it gets +2/+0 until end of turn for each other attacking Goblin."),
    ("Angelic Captain", "Flying\nWhenever this creature attacks, it gets +1/+1 until end of turn for each other attacking Ally."),
    ("Spider-Mobile", "Trample\nWhenever this creature attacks or blocks, it gets +1/+1 until end of turn for each Spider you control.\nCrew 2"),
])
def test_real_cards_are_modeled(name, oracle):
    card = Card(id=name, name=name, type_line="Creature — Goblin", is_creature=True,
                power=2, toughness=2, oracle_text=oracle)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
