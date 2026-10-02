"""RULE 123 Stickers — declared a permanent non-goal, not an ordinary gap.

Any card whose oracle text mentions "sticker" gets the `NEVER_SUPPORTED`
verdict (`gate._mentions_stickers`) instead of `UNMODELED`, so it never
contributes unclaimed clauses to the processing-list backlog and never binds
any behaviour (same fail-closed posture as an ordinary UNMODELED card).
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import NEVER_SUPPORTED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.processing_list import coverage_report
from mtg_analyzer.services import coverage_db as cov


def _card(name, text):
    return Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text)


def test_sticker_card_is_never_supported_not_unmodeled():
    card = _card(
        "Sticker Test Card",
        "You may reveal a card from your sticker sheet and put a sticker on a permanent.",
    )
    result = parse_oracle(card)
    assert result.coverage == NEVER_SUPPORTED
    assert result.never_supported is True
    assert result.modeled is False


def test_sticker_card_has_no_unclaimed_clauses():
    card = _card("Sticker Test Card 2", "Put a sticker on target creature you control.")
    result = parse_oracle(card)
    assert result.unclaimed == []


def test_sticker_mention_is_case_insensitive():
    card = _card("Sticker Test Card 3", "STICKER sheet nonsense that would otherwise be unclaimed.")
    result = parse_oracle(card)
    assert result.coverage == NEVER_SUPPORTED


@pytest.mark.parametrize("type_line", ["Stickers", "STICKERS", " stickers "])
@pytest.mark.parametrize("text", ["{TK}{TK} — 1/4", ""])
def test_sticker_sheet_is_never_supported_without_sticker_oracle_text(type_line, text):
    card = Card(id="sheet", name="Ancestral Hot Dog Minotaur", type_line=type_line,
                oracle_text=text)
    result = parse_oracle(card)
    assert result.coverage == NEVER_SUPPORTED
    assert not result.modeled
    assert result.specs == []
    assert result.unclaimed == []
    report = coverage_report([result])
    assert report.never_supported == 1
    assert report.processing_list == []


def test_sticker_sheet_does_not_inflate_card_coverage_denominator():
    from scripts.coverage_report import measure

    sheet = Card(id="sheet", name="Ancestral Hot Dog Minotaur", type_line="Stickers",
                 oracle_text="{TK}{TK} — 1/4")
    vanilla = Card(id="bear", name="Bear", type_line="Creature", oracle_text="")
    sticker_spell = _card("Sticker Spell", "Put a sticker on target creature.")
    total, covered, never_supported, templates, _, _ = measure(
        [sheet, vanilla, sticker_spell], None,
    )
    assert (total, covered, never_supported) == (2, 1, 2)
    assert not templates


def test_ordinary_unmodeled_card_is_unaffected():
    card = _card("Definitely Not A Sticker Card", "Do something the parser has never heard of, zzyzx.")
    result = parse_oracle(card)
    assert result.coverage == UNMODELED
    assert result.never_supported is False


def test_vanilla_card_stays_modeled():
    card = Card(id="Vanilla Bear", name="Vanilla Bear", type_line="Creature", is_creature=True,
                power=2, toughness=2, oracle_text="")
    result = parse_oracle(card)
    assert result.modeled is True
    assert result.never_supported is False


def test_never_supported_card_never_reaches_the_processing_list_backlog():
    card = _card(
        "Sticker Backlog Card",
        "Reveal the top card of your sticker sheet, then put a sticker on it, then do something else unmodeled.",
    )
    report = coverage_report([parse_oracle(card)])
    assert report.never_supported == 1
    assert report.modeled == 0
    assert report.processing_list == []


def test_coverage_db_source_constant_exists_for_ledger_writes():
    # Just a schema/constant sanity check — a fresh ledger row can carry the
    # NEVER_SUPPORTED verdict directly in its `coverage` column.
    assert cov.NEVER_SUPPORTED == "never_supported"
