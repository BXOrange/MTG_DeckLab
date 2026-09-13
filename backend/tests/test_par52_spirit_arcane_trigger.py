"""PAR-52 — Spirit-or-Arcane spell cast triggers."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def test_spirit_or_arcane_cast_trigger_parses_with_both_subtypes():
    card = Card(
        id="baku", name="Baku Altar", type_line="Artifact",
        oracle_text="Whenever you cast a Spirit or Arcane spell, you may put a ki counter on Baku Altar.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    [ability] = result.effect_specs
    assert ability.trigger["spell_subtype_any"] == ["spirit", "arcane"]


def test_teamwork_rider_is_a_cast_state_condition():
    [spec] = parse_effect_body("if this spell was cast using teamwork, draw a card")
    assert spec.condition == {"kind": "flag", "flag": "teamwork_paid"}
