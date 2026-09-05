"""Tests for the RULE 614.1 "enters tapped" land-clause recognition
(`parser/oracle/catalogue/lands.py`) — the single source of truth the
coverage gate (`gate.py`) and the engine (`game/ability_catalogue.
land_tap_condition`) both consult, so the shapes claimed and the shapes
resolved can never drift apart.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.lands import (
    tap_clause_condition,
    tapped_entry_choice_tail,
)

# ---------------------------------------------------------------------------
# tap_clause_condition — direct clause-shape classification
# ---------------------------------------------------------------------------


def test_plain_tapland_this_land():
    assert tap_clause_condition("this land enters tapped.") == {"kind": "always"}


def test_plain_tapland_enters_the_battlefield_tapped():
    assert tap_clause_condition("~ enters the battlefield tapped.") == {"kind": "always"}


def test_plain_tapland_enters_tapped_self_name():
    assert tap_clause_condition("~ enters tapped.") == {"kind": "always"}


def test_thriving_land_tapped_entry_and_choice_tail_are_both_recognized():
    line = "~ enters tapped. as it enters, choose a color other than red."
    assert tap_clause_condition(line) == {"kind": "always"}
    assert tapped_entry_choice_tail(line) == "as it enters, choose a color other than red"


def test_this_artifact_enters_tapped():
    assert tap_clause_condition("this artifact enters tapped.") == {"kind": "always"}


def test_this_creature_enters_tapped():
    assert tap_clause_condition("this creature enters tapped.") == {"kind": "always"}


def test_shock_land_pay_life():
    line = "as ~ enters the battlefield, you may pay 2 life. if you don't, it enters tapped."
    assert tap_clause_condition(line) == {"kind": "pay_life", "amount": 2}


def test_battlebond_unless_opponents():
    line = "this land enters tapped unless you have 2 or more opponents."
    assert tap_clause_condition(line) == {"kind": "unless_opponents", "count": 2}


def test_turbulent_land_unless_opponents_control_lands():
    # Distinct from `unless_opponents` (opponent *player* count) and
    # `unless_count` (the controller's *own* lands) — this one counts the
    # opponents' total lands.
    line = "this land enters tapped unless your opponents control 8 or more lands."
    assert tap_clause_condition(line) == {
        "kind": "unless_opponents_count",
        "cmp": "ge",
        "count": 8,
    }


def test_turbulent_land_fewer_variant():
    line = "this land enters tapped unless your opponents control 3 or fewer lands."
    assert tap_clause_condition(line) == {
        "kind": "unless_opponents_count",
        "cmp": "le",
        "count": 3,
    }


def test_fast_land_unless_count_fewer_other_lands():
    line = "this land enters tapped unless you control 2 or fewer other lands."
    assert tap_clause_condition(line) == {"kind": "unless_count", "cmp": "le", "count": 2}


def test_slow_land_unless_count_more_other_lands():
    line = "this land enters tapped unless you control 2 or more other lands."
    assert tap_clause_condition(line) == {"kind": "unless_count", "cmp": "ge", "count": 2}


def test_unless_count_more_basic_lands():
    line = "this land enters tapped unless you control 2 or more basic lands."
    assert tap_clause_condition(line) == {
        "kind": "unless_count",
        "cmp": "ge",
        "count": 2,
        "basic": True,
    }


def test_check_land_unless_types_single():
    line = "this land enters tapped unless you control a mountain."
    assert tap_clause_condition(line) == {"kind": "unless_types", "types": ["mountain"]}


def test_check_land_unless_types_multiple():
    line = "~ enters the battlefield tapped unless you control a mountain or a forest."
    assert tap_clause_condition(line) == {
        "kind": "unless_types",
        "types": ["mountain", "forest"],
    }


def test_non_matching_other_permanents_tap():
    # A tapped-entry that isn't about *this* permanent at all — a genuinely
    # different, unmodeled shape (fails closed).
    line = "artifacts your opponents control enter tapped."
    assert tap_clause_condition(line) is None


def test_non_matching_unrecognized_condition():
    # A conditional tapped-entry shape the engine doesn't resolve — must not
    # be claimed even though it starts like a recognized clause.
    line = "this land enters tapped unless you discard a card."
    assert tap_clause_condition(line) is None


def test_non_matching_plain_sentence():
    assert tap_clause_condition("target land you control becomes untapped.") is None


# ---------------------------------------------------------------------------
# Gate-level: a real tap-land card becomes MODELED without an effect spec
# ---------------------------------------------------------------------------


def _land(name, oracle_text):
    return Card(id=name, name=name, type_line="Land", is_land=True, oracle_text=oracle_text)


def test_gate_claims_plain_tapland_as_modeled():
    card = _land("Tranquil Cove", "Tranquil Cove enters the battlefield tapped.\n"
                                   "{T}: Add {W} or {U}.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    # Covered-without-spec, like a mana ability — no effect spec emitted for it.
    assert result.effect_specs == []


def test_gate_claims_thriving_land_and_keeps_its_enter_color_choice():
    card = _land(
        "Thriving Bluff",
        "This land enters tapped. As it enters, choose a color other than red.\n"
        "{T}: Add {R} or one mana of the chosen color.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    [choice] = [spec for spec in result.specs if spec.ability_kind == "enter_replacement"]
    assert choice.effects[0].type == "choose_color_on_enter"


def test_gate_claims_shock_land_as_modeled():
    card = _land(
        "Steam Vents",
        "As Steam Vents enters the battlefield, you may pay 2 life. "
        "If you don't, it enters tapped.\n{T}: Add {U} or {R}.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED


def test_gate_claims_battlebond_land_as_modeled():
    card = _land(
        "Bountiful Promenade",
        "This land enters tapped unless you have two or more opponents.\n"
        "{T}: Add {W} or {G}.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED


def test_gate_claims_basic_count_land_as_modeled():
    card = _land(
        "Hypothetical Basic-Counting Land",
        "This land enters tapped unless you control two or more basic lands.\n"
        "{T}: Add {B} or {G}.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED


def test_gate_claims_turbulent_land_as_modeled():
    card = _land(
        "Turbulent Fen",
        "This land enters tapped unless your opponents control eight or more lands.\n"
        "{T}: Add {B} or {R}.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED


def test_gate_does_not_claim_unrecognized_conditional_tap_line():
    card = _land(
        "Hypothetical Discard Land",
        "This land enters tapped unless you discard a card.\n{T}: Add {C}.",
    )
    result = parse_oracle(card)
    assert result.coverage != MODELED
    assert any("discard" in line for line in result.unclaimed)
