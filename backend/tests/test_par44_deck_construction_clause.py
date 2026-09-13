"""PAR-44 — RULE 100.2a's inert any-number deck-construction sentence."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.catalogue.static_handlers import deck_any_number_line


def test_any_number_deck_clause_is_claimed_without_a_runtime_ability():
    card = Card(
        id="rat", name="Relentless Rats", type_line="Creature — Rat", is_creature=True,
        oracle_text="A deck can have any number of cards named Relentless Rats.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.specs == []


def test_any_number_clause_full_matches_only_the_deckbuilding_sentence():
    assert deck_any_number_line("a deck can have any number of cards named ~.")
    assert not deck_any_number_line("a deck can have any number of cards named ~ and draw a card.")
