"""PAR-121: the subject-scope slot and the certain-antecedent connective, each declared once.

Pure maintainability: nothing here may change what a clause parses to. The pre-refactor reading of every
clause the 34,811-card cache reaches (39,639 clause × subject-flag readings) was fingerprinted before the
consolidation and compared after — 0 changed. These tests pin the same thing for the rows the corpus never
reaches (the verb × subject cells no printed card uses yet), with the exact specs the per-subject builders
used to emit.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle.catalogue.handlers import HANDLERS, match_clause
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec

ENTERING = {"of": "entering", "as": "controller"}
ATTACHED = {"of": "attached", "as": "controller"}


@pytest.mark.parametrize("clause, flag, expected", [
    ("its controller loses 2 life", "group_subject", EffectSpec("lose_life", {"amount": 2, "player": ENTERING})),
    ("its controller gains 3 life", "group_subject", EffectSpec("gain_life", {"amount": 3, "player": ENTERING})),
    ("its controller gains that much life", "group_subject",
     EffectSpec("gain_life", {"amount_from_trigger_event": "amount", "player": ENTERING})),
    ("its controller draws 2 cards", "group_subject", EffectSpec("draw", {"count": 2, "player": ENTERING})),
    ("its controller discards a card", "group_subject", EffectSpec("discard", {"count": 1, "player": ENTERING})),
    ("its controller mills 4 cards", "group_subject",
     EffectSpec("mill", {"count": 4, "selector": "trigger_subject_controller"})),
    ("its controller loses 2 life", "attached_subject", EffectSpec("lose_life", {"amount": 2, "player": ATTACHED})),
    ("its controller loses that much life", "attached_subject",
     EffectSpec("lose_life", {"amount_from_trigger_event": "amount", "player": ATTACHED})),
    ("its controller gains 3 life", "attached_subject", EffectSpec("gain_life", {"amount": 3, "player": ATTACHED})),
    ("its controller draws a card", "attached_subject", EffectSpec("draw", {"count": 1, "player": ATTACHED})),
    ("its controller discards 2 cards", "attached_subject", EffectSpec("discard", {"count": 2, "player": ATTACHED})),
    ("its controller mills 3 cards", "attached_subject",
     EffectSpec("mill", {"count": 3, "selector": "attached_permanent_controller"})),
])
def test_its_controller_verb_subject_matrix_emits_what_each_builder_used_to(clause, flag, expected):
    assert match_clause(clause, **{flag: True}) == [expected]


@pytest.mark.parametrize("flag, player", [("group_subject", ENTERING), ("attached_subject", ATTACHED)])
def test_its_controller_sacrifices_reads_the_subject_operand(flag, player):
    [spec] = match_clause("its controller sacrifices a nontoken creature of their choice", **{flag: True})
    assert spec == EffectSpec("sacrifice", {"what": "nontoken_creature", "count": 1, "player": player})


def test_a_matrix_row_is_only_offered_under_its_own_subject():
    assert match_clause("its controller gains that much life", attached_subject=True) is None  # polarity is group-only
    assert match_clause("its controller loses that much life", group_subject=True) is None  # …and this one attached-only
    assert match_clause("its controller draws 2 cards") is None  # a bare pronoun claims nothing alone


def test_the_matrix_rows_keep_their_names_and_order():
    names = [h.name for h in HANDLERS if h.name.startswith(("group_its_controller", "attached_its_controller"))]
    assert names == [
        "group_its_controller_loses_life", "group_its_controller_gains_life",
        "group_its_controller_gains_that_much_life", "group_its_controller_draws",
        "group_its_controller_discards", "group_its_controller_mills", "group_its_controller_sacrifices",
        "attached_its_controller_loses_life", "attached_its_controller_loses_that_much_life",
        "attached_its_controller_gains_life", "attached_its_controller_draws",
        "attached_its_controller_discards", "attached_its_controller_mills",
        "attached_its_controller_sacrifices",
    ]


def test_the_subject_flag_of_each_generated_row():
    by_name = {h.name: h for h in HANDLERS}
    assert by_name["group_its_controller_draws"].group_subject_only
    assert by_name["attached_its_controller_draws"].attached_subject_only
    assert by_name["double_pt_previous"].previous_subject_only
    assert by_name["double_pt_self_pronoun"].self_subject_only
    assert by_name["pump_group_subject_x"].group_subject_only
    assert by_name["gain_life_eq_that_group"].group_subject_only
    assert not by_name["attach_chosen_to_source"].self_subject_only


@pytest.mark.parametrize("body", [
    "sacrifice ~. when you do, draw a card",
    "sacrifice ~. if you do, draw a card",
    "earthbend 2. when you do, draw a card",
    "discard a card. if you do, draw a card",
    "discard a card. when you do, draw a card",
])
def test_certain_antecedent_collapses_to_a_sequence(body):
    specs = parse_effect_body(body)
    assert specs is not None and specs[-1].type == "draw"
    assert len(specs) == 2


@pytest.mark.parametrize("body", [
    "earthbend 2. if you do, draw a card",        # the earthbend row is "when you do" only
    "sacrifice target creature. when you do, draw a card",  # not the certain self-sacrifice
    "discard a card at random. if you do, draw a card",     # not a bare mandatory discard
])
def test_certain_antecedent_rows_keep_their_narrow_connectives(body):
    assert parse_effect_body(body) is None


def test_exile_another_target_is_the_plain_exile_row():
    assert "exile_another_target" not in {h.name for h in HANDLERS}
    [spec] = match_clause("exile another target creature")
    assert spec == EffectSpec("exile", {"target_kind": "creature"})
    [spec] = match_clause("exile another target nonland permanent")
    assert spec.params["target_kind"] == "nonland_permanent"


@pytest.mark.parametrize("clause, params", [
    ("~ deals 3 damage to target tapped creature",
     {"amount": 3, "target_kind": "creature", "creature_filter": {"tapped": True}}),
    ("~ deals x damage to up to one target creature",
     {"amount": "x", "target_kind": "creature", "optional": True}),
    ("it deals that much damage to any target",
     {"amount_from_trigger_event": "that_much", "target_kind": "any"}),
    ("~ deals damage equal to that spell's mana value to target creature",
     {"amount_from_trigger_event": "mana_value", "target_kind": "creature"}),
])
def test_targeted_damage_builders_share_one_shape(clause, params):
    assert match_clause(clause, self_subject=True) == [EffectSpec("damage", params)]
