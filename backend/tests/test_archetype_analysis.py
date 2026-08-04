"""Tests for services/archetype_database.py and services/archetype_analysis.py.

Reference: docs/implementation-state/BACKLOG.md's archetype-analysis
request; the archetype catalogue itself is `mtg_analyzer/data/archetypes
.json`. These tests don't assert exact percentages (the scoring thresholds
are a hand-tuned first pass, documented as such in `archetype_analysis.py`)
— they assert the *ordering*/*shape* a correct heuristic must produce: a
deck built entirely from one archetype's own staples must score that
archetype highest, and an archetype with none of its signals present must
score nowhere near 100.
"""

import json

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.archetype_analysis import (
    TYPAL_MIN_CREATURE_SHARE,
    detect_typal_signals,
    score_archetypes,
)
from mtg_analyzer.services.archetype_database import ArchetypeDatabase, default_archetype_database


def make_card(name, **kw):
    defaults = dict(id=name, name=name, type_line="Sorcery")
    defaults.update(kw)
    return Card(**defaults)


def make_creature(name, subtypes, **kw):
    defaults = dict(
        id=name,
        name=name,
        type_line=f"Creature — {subtypes}",
        is_creature=True,
        power=1,
        toughness=1,
    )
    defaults.update(kw)
    return Card(**defaults)


def make_land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


class TestArchetypeDatabase:
    def test_default_catalogue_loads_and_has_entries(self):
        db = default_archetype_database()
        assert len(db) > 0
        entries = db.all_archetypes()
        assert all({"id", "label", "signal_cards", "synergy_patterns", "score_threshold"} <= e.keys() for e in entries)

    def test_get_known_and_unknown_id(self):
        db = default_archetype_database()
        assert db.get("aristocrats") is not None
        assert db.get("not-a-real-archetype") is None

    def test_ids_are_unique(self):
        db = default_archetype_database()
        ids = [e["id"] for e in db.all_archetypes()]
        assert len(ids) == len(set(ids))

    def test_missing_field_raises(self, tmp_path):
        bad = [{"id": "x", "label": "X"}]  # missing required fields
        path = tmp_path / "archetypes.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            ArchetypeDatabase(path)

    def test_duplicate_id_raises(self, tmp_path):
        entry = {
            "id": "dup",
            "label": "Dup",
            "description": "",
            "signal_cards": {"core": [], "support": []},
            "synergy_patterns": [],
            "win_condition_cards": [],
            "score_threshold": 10,
        }
        path = tmp_path / "archetypes.json"
        path.write_text(json.dumps([entry, entry]), encoding="utf-8")
        with pytest.raises(ValueError):
            ArchetypeDatabase(path)


class TestScoreArchetypes:
    def test_aristocrats_deck_scores_aristocrats_highest(self):
        db = default_archetype_database()
        aristocrats = db.get("aristocrats")
        cards = [
            make_card(name, oracle_text="Whenever a creature you control dies, each opponent loses 1 life.")
            for name in aristocrats["signal_cards"]["core"]
        ] + [make_card(name) for name in aristocrats["signal_cards"]["support"]]

        scores = score_archetypes(cards)
        assert scores, "expected at least one scored archetype back"
        assert scores[0].id == "aristocrats"
        assert scores[0].percent == 100
        # A deck built purely from aristocrats staples shouldn't also read
        # as e.g. Storm just because both archetypes exist in the catalogue.
        storm_score = next((s for s in scores if s.id == "storm"), None)
        if storm_score is not None:
            assert storm_score.percent < scores[0].percent

    def test_unrelated_deck_scores_low_everywhere(self):
        cards = [make_land(f"Forest {i}") for i in range(20)]
        scores = score_archetypes(cards)
        assert all(s.percent < 50 for s in scores)

    def test_duplicate_copies_do_not_inflate_pattern_score(self):
        # 20 copies of the same nonland card should count once for pattern
        # matching, not 20x — otherwise deck size alone could fake a high
        # score (see PATTERN_MATCH_CAP's docstring).
        card = make_card("Repeatable Ritual", oracle_text="Sacrifice a creature: draw a card.")
        scores_one = score_archetypes([card])
        scores_many = score_archetypes([card] * 20)
        one = next(s for s in scores_one if s.id == "aristocrats")
        many = next(s for s in scores_many if s.id == "aristocrats")
        assert one.percent == many.percent

    def test_returns_at_most_top_n(self):
        from mtg_analyzer.services.archetype_analysis import TOP_N_SUGGESTIONS

        scores = score_archetypes([make_land()])
        assert len(scores) <= TOP_N_SUGGESTIONS


class TestDetectTypalSignals:
    def test_dominant_creature_type_is_reported(self):
        cards = [make_creature(f"Elf {i}", "Elf Warrior") for i in range(6)] + [
            make_creature("Odd One Out", "Human Wizard")
        ]
        signals = detect_typal_signals(cards)
        elf = next((s for s in signals if s.creature_type == "Elf"), None)
        assert elf is not None
        assert elf.count == 6
        assert elf.share >= TYPAL_MIN_CREATURE_SHARE

    def test_minority_type_is_not_reported(self):
        cards = [make_creature(f"Human {i}", "Human Soldier") for i in range(9)] + [
            make_creature("Lone Elf", "Elf Warrior")
        ]
        signals = detect_typal_signals(cards)
        assert all(s.creature_type != "Elf" for s in signals)

    def test_no_creatures_returns_empty(self):
        assert detect_typal_signals([make_card("Sol Ring")]) == []
