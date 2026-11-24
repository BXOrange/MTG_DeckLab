"""PAR-284 milestone 20: aggregate amounts in effect hosts (RULE 205.3m, 208.1, 702.73a).

"the greatest number of creatures you control that have a creature type in common" (the existing selector-level ``share``,
now also said with its own superlative) and "the greatest power and/or toughness among other creatures you control"
(`power_or_toughness`, the larger number on any one object).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_amounts import amount_of
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_referent_counts import _on_battlefield
from tests.test_par284_this_way_windows import _card, _engine

RAVAGER = "When this creature enters, it deals X damage to any target, where X is the greatest number of creatures you control that have a creature type in common."
MUSCLE = "Whenever this creature attacks or blocks, it gets +X/+X until end of turn, where X is the greatest power and/or toughness among other creatures you control."


def _creature(eng, name, type_line, power=1, toughness=1, owner="p1", oracle=""):
    return _on_battlefield(eng, _card(name, type_line, oracle, is_creature=True, power=power, toughness=toughness), owner=owner)


def _measured(oracle, eng, source):
    spec = parse_oracle(_card("Probe", "Creature — Beast", oracle, is_creature=True, power=1, toughness=1)).specs[0]
    bind = spec.effects[0]
    assert bind.type == "bind"
    return amount_of(bind.params["amount"], eng.rules.context, source, None)


def test_real_wordings_are_modeled():
    for oracle in (RAVAGER, MUSCLE):
        result = parse_oracle(_card("Probe", "Creature — Beast", oracle, is_creature=True, power=1, toughness=1))
        assert result.modeled, result.unclaimed
    modal = ("When this creature enters, choose one —\n• Each opponent loses X life, where X is the greatest number of creatures you control "
             "that have a creature type in common.\n• You gain X life, where X is the greatest number of creatures you control that have a "
             "creature type in common.")
    assert parse_oracle(_card("Shadowsage", "Creature — Elf", modal, is_creature=True, power=1, toughness=1)).modeled


def test_largest_group_of_a_shared_creature_type_counts_a_changeling_in_every_group():
    eng = _engine()
    ravager = _creature(eng, "Ravager", "Creature — Dwarf Berserker", oracle=RAVAGER)
    assert _measured(RAVAGER, eng, ravager) == 1  # itself
    _creature(eng, "Bear A", "Creature — Bear")
    _creature(eng, "Bear B", "Creature — Bear")
    _creature(eng, "Rival Bear", "Creature — Bear", owner="p2")  # not yours
    assert _measured(RAVAGER, eng, ravager) == 2
    shapeshifter = _creature(eng, "Shapeshifter", "Creature — Shapeshifter")
    shapeshifter.intrinsic_keywords.add("changeling")  # RULE 702.73a: it has every creature type
    assert _measured(RAVAGER, eng, ravager) == 3  # the changeling is a Bear (and a Dwarf, ...) too


def test_greatest_power_and_or_toughness_takes_the_larger_number_of_any_one_other_creature():
    eng = _engine()
    muscle = _creature(eng, "Muscle", "Creature — Human", power=9, toughness=9, oracle=MUSCLE)  # never counts itself
    _creature(eng, "Wall", "Creature — Wall", power=0, toughness=7)
    _creature(eng, "Brute", "Creature — Ogre", power=5, toughness=1)
    assert _measured(MUSCLE, eng, muscle) == 7
    _creature(eng, "Giant", "Creature — Giant", power=6, toughness=3, owner="p2")  # not yours
    assert _measured(MUSCLE, eng, muscle) == 7


def test_the_superlative_needs_a_shared_type_group():
    assert parse_effect_body("~ deals x damage to any target, where x is the greatest number of creatures you control.") is None
