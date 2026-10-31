"""Sentence splitting of the find-fragments skill script."""

import importlib.util
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parents[2]
           / ".claude" / "skills" / "find-fragments" / "scripts" / "find_fragments.py")
_spec = importlib.util.spec_from_file_location("find_fragments", _SCRIPT)
find_fragments = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(find_fragments)


def test_splits_on_sentence_boundaries():
    clause = "look at the top 2 cards of your library. put one into your hand. ~ gains haste."
    assert find_fragments.split_sentences(clause) == [
        "look at the top 2 cards of your library.",
        "put one into your hand.",
        "~ gains haste.",
    ]


def test_keeps_costs_and_table_rows_together():
    assert find_fragments.split_sentences("{t}: add {g}.") == ["{t}: add {g}."]
    assert find_fragments.split_sentences("1—9 | you gain 2 life.") == ["1—9 | you gain 2 life."]


def test_single_sentence_clause_is_one_fragment():
    (frag,) = find_fragments.sentence_fragments("some unmodeled single sentence nobody claims.")
    assert frag["sentences"] == 1 and frag["previous_sentence"] is None


def test_rank_templates_counts_only_fully_unlocked_cards():
    rows = [
        {"card": "A", "template": "t1", "clause": "c1"},
        {"card": "B", "template": "t1", "clause": "c1"},
        {"card": "B", "template": "t2", "clause": "c2"},
    ]
    ranked = {r["template"]: r for r in find_fragments.rank_templates(rows)}
    assert ranked["t1"]["marginal"] == 1  # A unlocked; B still needs t2


def test_phrase_regex_widens_placeholders():
    rx = find_fragments.phrase_regex("base power and toughness <n> / <n>")
    assert rx.search("it has base power and toughness 4/4.")
    assert not rx.search("it has power and toughness 4/4.")


def test_ablate_marks_removable_modifier():
    rows = [{"clause": "~ gets +1/+1 until end of turn."}]
    phrases = [{"phrase": "until end of turn"}]
    find_fragments.ablate(rows, phrases)
    assert phrases[0]["ablated"] == 1
