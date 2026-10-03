"""Shared optional loot grammar preserves the existing interactive discard delta."""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import parse_oracle


@pytest.mark.parametrize("text", [
    "Discard up to two cards, then draw that many cards.",
    "You may discard up to two cards. If you do, draw that many cards.",
    "When this creature enters, discard up to two cards, then draw that many cards.",
])
def test_loot_forms_parse(text):
    trigger = text.startswith("When")
    card = Card(id="loot", name="Looter", type_line="Creature" if trigger else "Sorcery",
                is_creature=trigger, is_sorcery=not trigger, oracle_text=text)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_unrelated_draw_count_does_not_match():
    card = Card(id="loot", name="Looter", type_line="Sorcery", is_sorcery=True,
                oracle_text="Discard up to two cards, then draw that many cards plus one.")
    assert not parse_oracle(card).modeled
