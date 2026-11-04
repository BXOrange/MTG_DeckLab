"""The shared full-pool pass must really observe cold parses and restore globals."""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle import gate
from mtg_analyzer.parser.oracle.catalogue import handlers as H
from tests.support.full_cache import observe_card_pool


def _card():
    return Card(id="scan-test", name="Scan test", type_line="Sorcery", is_sorcery=True,
                oracle_text="Draw a card.")


def test_warm_input_still_records_clauses_and_publishes_fresh_results(monkeypatch):
    memo = {}
    monkeypatch.setattr(gate, "_PARSE_CACHE", memo)
    card = _card()
    assert gate.parse_oracle(card).modeled
    original_match = H._match_clause_once
    scan = observe_card_pool([card])
    assert scan.cards == (card,)
    assert any(clause == "draw a card" for clause, _ in scan.clauses)
    assert H._match_clause_once is original_match
    assert gate._PARSE_CACHE is memo
    result = gate.parse_oracle(card)
    assert result.specs
    result.specs.clear()
    assert gate.parse_oracle(card).specs  # consumers cannot mutate the warmed memo


def test_failed_scan_restores_hook_and_memo_without_publishing_partial_results(monkeypatch):
    memo = {"sentinel": object()}
    monkeypatch.setattr(gate, "_PARSE_CACHE", memo)
    original_match = H._match_clause_once

    def broken_parse(card):
        assert gate._PARSE_CACHE is not memo
        assert H._match_clause_once is not original_match
        gate._PARSE_CACHE["partial"] = object()
        raise RuntimeError("injected parse failure")

    monkeypatch.setattr(gate, "parse_oracle", broken_parse)
    with pytest.raises(RuntimeError, match="injected parse failure"):
        observe_card_pool([_card()])
    assert gate._PARSE_CACHE is memo and set(memo) == {"sentinel"}
    assert H._match_clause_once is original_match
