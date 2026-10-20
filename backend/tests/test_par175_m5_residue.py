"""PAR-175 M5: residue-aware sequencing is a report, never a repair.

An unclaimed line keeps its card `UNMODELED`; the gate additionally records the minimal sentence or
"then"-connector part that blocked it (`ParseResult.unclaimed_spans`), and the processing list can rank by
that part instead of the whole line.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import coverage_over_cards, coverage_report, unclaimed_work_units
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle, unclaimed_spans
from mtg_analyzer.parser.oracle.residue import minimal_unclaimed_span, split_parts

BAD = "frobnicate the quux with wibbles."


def _card(name, oracle, type_line="Sorcery"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_sorcery=type_line == "Sorcery")


def _spans(card):
    result = parse_oracle(card)
    return result, {s.line: s.span for s in unclaimed_spans(card, result)}


def _only(result, spans):
    (line,) = result.unclaimed
    return line, spans[line]


def test_one_bad_sentence_among_good_ones_is_the_span():
    result, spans = _spans(_card("Test Middle", f"Draw a card. {BAD} You gain 2 life."))
    assert result.coverage == UNMODELED
    line, span = _only(result, spans)
    assert line == f"draw a card. {BAD} you gain 2 life."  # `unclaimed` keeps the whole normalised line
    assert span == BAD


def test_bad_trailing_sentence_behind_a_trigger_head_keeps_the_head():
    result, spans = _spans(_card("Test Trigger", f"When this creature enters, draw a card. {BAD}", "Creature — Wizard"))
    assert result.coverage == UNMODELED
    assert _only(result, spans)[1] == BAD


def test_bad_connector_part_is_the_span():
    result, spans = _spans(_card("Test Then", "Draw a card, then frobnicate the quux."))
    assert result.coverage == UNMODELED
    assert _only(result, spans)[1] == "frobnicate the quux."


def test_fully_unclaimed_line_is_its_own_span():
    result, spans = _spans(_card("Test Whole", f"{BAD} Quux the frobnicator."))
    assert result.coverage == UNMODELED
    line, span = _only(result, spans)
    assert span == line


def test_single_sentence_line_is_its_own_span():
    result, spans = _spans(_card("Test Single", BAD))
    line, span = _only(result, spans)
    assert span == line == BAD


def test_modeled_card_has_no_spans():
    card = _card("Test Good", "Draw a card. You gain 2 life.")
    result = parse_oracle(card)
    assert result.coverage == MODELED
    assert result.unclaimed == [] and unclaimed_spans(card, result) == []


def test_two_bad_parts_fall_back_to_the_whole_line():
    result, spans = _spans(_card("Test Two", f"{BAD} Draw a card. Quux the frobnicator."))
    line, span = _only(result, spans)
    assert span == line


def test_quoted_sentences_are_not_split():
    parts = split_parts('Create a token with "Draw a card. Discard a card." Gain 1 life.')
    assert [t for _s, t in parts] == ['Create a token with "Draw a card. Discard a card."', "Gain 1 life."]


def test_span_probe_is_pure_data_with_a_stub_claimer():
    claims = lambda text: "Bad" not in text  # noqa: E731
    assert minimal_unclaimed_span("Good one. Bad one. Good two.", claims) == "Bad one."
    assert minimal_unclaimed_span("Good one.", claims) == "Good one."


def test_ranking_groups_by_sentence_not_by_line():
    cards = [
        _card("Test A", f"Draw a card. {BAD}"),
        _card("Test B", f"You gain 2 life. {BAD}"),
        _card("Test C", f"Draw two cards. {BAD}"),
    ]
    results = [parse_oracle(c) for c in cards]
    assert [unclaimed_work_units(c, r) for c, r in zip(cards, results)] == [[BAD]] * 3
    by_line = coverage_report(results).processing_list
    by_span = coverage_over_cards(cards, by_span=True).processing_list
    assert len(by_line) == 3 and all(e.cards == 1 for e in by_line)
    assert [(e.template, e.cards) for e in by_span] == [(BAD, 3)]
    assert coverage_report(results).modeled == coverage_over_cards(cards, by_span=True).modeled == 0


def test_parse_result_carries_no_span_data():
    # Spans are computed on demand, never inside `parse_oracle` (about +40% on a full-cache parse).
    assert not hasattr(parse_oracle(_card("Test Lazy", BAD)), "unclaimed_spans")


def test_untap_that_creature_prefers_the_previous_target_over_the_trigger_creature():
    # RULE 608.2c: with a group-subject trigger AND an earlier pick, "that creature" is the nearest antecedent.
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    both = match_clause("untap that creature", reading=ClauseReading(group_subject=True, previous_subject=True))
    assert both is not None and both[0].params.get("previous_subject") is True
    group_only = match_clause("untap that creature", reading=ClauseReading(group_subject=True))
    assert group_only is not None and not group_only[0].params.get("previous_subject")
