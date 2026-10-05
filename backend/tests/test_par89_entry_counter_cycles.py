"""PAR-89 — named counter cycles and hand-cast Myojin entry condition."""

from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition
from mtg_analyzer.parser.oracle.catalogue.lands import tap_clause_condition


def test_tapped_counter_land_cycles_have_both_entry_replacements():
    for line, kind in [
        ("~ enters tapped with 2 charge counters on it.", "charge"),
        ("~ enters tapped with 2 depletion counters on it.", "depletion"),
    ]:
        assert tap_clause_condition(line) == {"kind": "always"}
        assert entry_counters_condition(line) == {
            "is_x": False, "count": 2, "counter_type": kind,
        }


def test_myojin_counter_requires_a_hand_cast():
    assert entry_counters_condition(
        "~ enters with a divinity counter on it if you cast it from your hand."
    ) == {"is_x": False, "count": 1, "counter_type": "divinity", "cast_from_hand_gate": True}
