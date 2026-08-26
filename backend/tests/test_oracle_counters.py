"""Tests for the RULE 614.1-style "enters with N counters" clause
recognition (`parser/oracle/catalogue/counters.py`) — the single source of
truth the coverage gate (`gate.py`) and the engine
(`game/ability_catalogue.entry_counters`) both consult, so the shapes
claimed and the shapes resolved can never drift apart.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.parser.oracle import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition

# ---------------------------------------------------------------------------
# entry_counters_condition — direct clause-shape classification
# ---------------------------------------------------------------------------


def test_fixed_plus_one_counters_this_creature():
    line = "this creature enters with 3 +1/+1 counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 3,
        "counter_type": "+1/+1",
    }


def test_fixed_single_counter_via_a():
    line = "this creature enters with a +1/+1 counter on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 1,
        "counter_type": "+1/+1",
    }


def test_fixed_bare_word_counter_type():
    line = "this creature enters with 4 ice counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 4,
        "counter_type": "ice",
    }


def test_fixed_counter_on_an_artifact():
    line = "this artifact enters with 3 charge counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 3,
        "counter_type": "charge",
    }


def test_x_amount_plus_one_counters():
    line = "this creature enters with x +1/+1 counters on it."
    assert entry_counters_condition(line) == {"is_x": True, "counter_type": "+1/+1"}


def test_x_amount_on_an_enchantment_bare_word():
    line = "this enchantment enters with x charge counters on it."
    assert entry_counters_condition(line) == {"is_x": True, "counter_type": "charge"}


def test_self_name_folded_subject():
    line = "~ enters with x +1/+1 counters on it."
    assert entry_counters_condition(line) == {"is_x": True, "counter_type": "+1/+1"}


def test_enters_the_battlefield_phrasing():
    line = "this creature enters the battlefield with 2 +1/+1 counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 2,
        "counter_type": "+1/+1",
    }


def test_minus_one_counters():
    line = "this creature enters with 2 -1/-1 counters on it."
    assert entry_counters_condition(line) == {
        "is_x": False,
        "count": 2,
        "counter_type": "-1/-1",
    }


def test_unrelated_line_is_not_claimed():
    assert entry_counters_condition("this creature enters tapped.") is None
    assert entry_counters_condition("draw a card.") is None


def test_extra_trailing_text_is_not_claimed():
    # Fail-closed: a recognized shape with unrecognized text tacked on must
    # not be silently claimed.
    line = "this creature enters with 3 +1/+1 counters on it and gains haste."
    assert entry_counters_condition(line) is None


# ---------------------------------------------------------------------------
# Coverage-gate integration — the clause is claimed without an effect spec
# ---------------------------------------------------------------------------


def creature(name, text, cost="{2}{G}", extra_lines=""):
    oracle = text if not extra_lines else f"{text}\n{extra_lines}"
    return Card(
        id=name, name=name, type_line="Creature — Beast",
        mana_cost_string=cost, is_creature=True, power=1, toughness=1,
        oracle_text=oracle,
    )


def test_solo_entry_counters_clause_is_fully_modeled():
    card = creature("Steady Beast", "This creature enters with 3 +1/+1 counters on it.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_x_entry_counters_clause_is_fully_modeled():
    card = creature(
        "X Beast", "This creature enters with X +1/+1 counters on it.", cost="{X}{G}"
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == []


def test_entry_counters_clause_does_not_mask_other_unclaimed_lines():
    # A card with a genuinely unmodeled second line stays UNMODELED — the
    # entry-counters clause is claimed, but claiming it can't paper over an
    # unrelated gap elsewhere on the card (fail-closed, docs/09).
    card = creature(
        "Compound Beast",
        "This creature enters with 3 +1/+1 counters on it.",
        extra_lines="Regenerate this creature.",
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED
    # "this creature" folds to the self-reference "~" in normalisation
    # (`normalize._fold_self_reference`); the line is still genuinely unclaimed.
    assert "regenerate ~." in result.unclaimed
    assert not any("enters with" in line for line in result.unclaimed)
