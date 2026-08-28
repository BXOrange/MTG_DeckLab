"""Tests for the persistent engineering coverage ledger.

Reference: services/coverage_db.py — the anti-duplicate-work ledger that keys on
the parser's own content signature so a re-measure only re-parses changed cards.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.services import coverage_db as cov


def _card(name="Lightning Bolt", oracle_text="Deal 3 damage to any target.", **extra):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                oracle_text=oracle_text, **extra)


class TestContentHash:
    def test_stable_for_same_content(self):
        c = _card()
        assert cov.content_hash(c) == cov.content_hash(_card())

    def test_changes_when_oracle_text_changes(self):
        assert cov.content_hash(_card()) != cov.content_hash(_card(oracle_text="Draw a card."))

    def test_changes_with_parser_version(self):
        c = _card()
        assert cov.content_hash(c, "1") != cov.content_hash(c, "2")


class TestUpsertAndGet:
    def test_roundtrips_a_coverage_row(self):
        db = cov.CoverageDatabase(":memory:")
        h = cov.content_hash(_card())
        db.upsert(h, "Lightning Bolt", cov.MODELED, "parser", [])
        row = db.get(h)
        assert row is not None
        assert row.name == "Lightning Bolt"
        assert row.coverage == cov.MODELED
        assert row.covered is True

    def test_authored_counts_as_covered_even_if_unmodeled(self):
        db = cov.CoverageDatabase(":memory:")
        h = cov.content_hash(_card())
        db.upsert(h, "Weird Card", cov.UNMODELED, "authored", ["some clause"])
        row = db.get(h)
        assert row.covered is True  # authored cards behave despite parser miss

    def test_unmodeled_parser_card_is_not_covered(self):
        db = cov.CoverageDatabase(":memory:")
        h = cov.content_hash(_card())
        db.upsert(h, "Uncovered", cov.UNMODELED, "parser", ["clause a", "clause b"])
        row = db.get(h)
        assert row.covered is False
        assert row.unclaimed == ["clause a", "clause b"]

    def test_missing_hash_returns_none(self):
        db = cov.CoverageDatabase(":memory:")
        assert db.get("deadbeef") is None

    def test_counts_totals_and_covered(self):
        db = cov.CoverageDatabase(":memory:")
        db.upsert("h1", "A", cov.MODELED, "parser", [])
        db.upsert("h2", "B", cov.UNMODELED, "parser", ["x"])
        db.upsert("h3", "C", cov.UNMODELED, "authored", ["y"])
        assert db.counts() == (3, 2)


class TestSnapshotsAndTemplates:
    def test_records_and_reads_back_a_snapshot(self):
        db = cov.CoverageDatabase(":memory:")
        db.record_snapshot(total=100, covered=40, top_templates=[("deal <n> damage", 5)])
        latest = db.latest_snapshots(1)
        assert latest[0]["total"] == 100
        assert latest[0]["covered"] == 40
        assert abs(latest[0]["fraction"] - 0.4) < 1e-9

    def test_handled_templates_ledger(self):
        db = cov.CoverageDatabase(":memory:")
        db.mark_template_handled("choose <n> —", handler="modal_choose_n")
        assert db.handled_templates() == {"choose <n> —": "modal_choose_n"}


class _StubRawStore:
    """Duck-typed `RawCardStore` stand-in — `commander_legal_names` only
    ever calls `iter_raw()`, per its own docstring."""

    def __init__(self, rows):
        self._rows = rows

    def iter_raw(self):
        return iter(self._rows)


class TestCommanderLegalNames:
    def test_legal_and_restricted_are_included(self):
        store = _StubRawStore([
            {"name": "Sol Ring", "legalities": {"commander": "legal"}},
            {"name": "Gifts Ungiven", "legalities": {"commander": "restricted"}},
        ])
        assert cov.commander_legal_names(store) == {"Sol Ring", "Gifts Ungiven"}

    def test_banned_and_not_legal_are_excluded(self):
        store = _StubRawStore([
            {"name": "Mana Crypt", "legalities": {"commander": "legal"}},
            {"name": "Sway of the Stars", "legalities": {"commander": "banned"}},
            {"name": "Some Un-set Card", "legalities": {"commander": "not_legal"}},
        ])
        assert cov.commander_legal_names(store) == {"Mana Crypt"}

    def test_missing_legalities_data_is_excluded_not_crashed_on(self):
        store = _StubRawStore([
            {"name": "Sol Ring", "legalities": {"commander": "legal"}},
            {"name": "No Legalities Field"},
            {"name": "Null Legalities", "legalities": None},
        ])
        assert cov.commander_legal_names(store) == {"Sol Ring"}
