"""Tests for the lazy Commander Spellbook snapshot and SQLite diffing."""

import gzip
import json

import httpx2 as httpx
import pytest

from mtg_analyzer.services import commander_spellbook_database as spellbook
from mtg_analyzer.services.commander_spellbook_database import CommanderSpellbookDatabase


def _variant(variant_id, cards, *, produces=(), requirements=(), identity=""):
    return {
        "id": variant_id,
        "status": "OK",
        "identity": identity,
        "uses": [
            {"card": {"name": name}, "quantity": quantity}
            for name, quantity in cards
        ],
        "produces": [
            {"feature": {"name": feature}, "quantity": 1} for feature in produces
        ],
        "requires": [
            {"template": {"name": name}, "quantity": 1} for name in requirements
        ],
    }


def _write_snapshot(path, variants, *, aliases=(), version="1.0", timestamp="2025-01-01"):
    payload = {
        "timestamp": timestamp,
        "version": version,
        "variants": variants,
        "aliases": list(aliases),
    }
    with gzip.open(path, "wt", encoding="utf-8") as output:
        json.dump(payload, output)
    return path


class TestCommanderSpellbookDatabase:
    def test_ingests_uncompressed_json_snapshot(self, tmp_path):
        snapshot_path = tmp_path / "snapshot.json"
        snapshot_path.write_text(
            json.dumps(
                {
                    "timestamp": "2025-01-01",
                    "version": "1.0",
                    "variants": [_variant("combo-1", [("Alpha", 1)])],
                    "aliases": [],
                }
            ),
            encoding="utf-8",
        )
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")

        result = database.ingest_snapshot(snapshot_path)

        assert result["variantCount"] == 1
        assert [combo["id"] for combo in database.matches([{"name": "Alpha"}])] == ["combo-1"]

    def test_status_does_not_create_or_download_database(self, tmp_path):
        path = tmp_path / "spellbook.sqlite"
        database = CommanderSpellbookDatabase(path)

        assert database.status() == {
            "initialized": False,
            "variantCount": 0,
            "aliasCount": 0,
            "version": None,
            "sourceTimestamp": None,
            "lastSyncedAt": None,
        }
        assert not path.exists()

    def test_first_match_lazily_downloads_and_matches_case_insensitive_names(
        self, tmp_path, monkeypatch
    ):
        snapshot = _write_snapshot(
            tmp_path / "snapshot.json.gz",
            [
                _variant(
                    "combo-1",
                    [("Alpha", 1), ("Beta", 1)],
                    produces=("Infinite mana",),
                    requirements=("You control a creature",),
                ),
                _variant("combo-2", [("Alpha", 2), ("Beta", 1)]),
            ],
        )
        snapshot_bytes = snapshot.read_bytes()
        requests = []
        client_type = httpx.Client

        def handler(request):
            requests.append(request)
            return httpx.Response(200, content=snapshot_bytes)

        monkeypatch.setattr(
            spellbook.httpx,
            "Client",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")

        matches = database.matches([{"name": "aLpHa", "quantity": 1}, {"name": "Beta"}])

        assert len(requests) == 1
        assert len(matches) == 1
        assert matches[0]["id"] == "combo-1"
        assert matches[0]["producesInfinite"] is True
        assert matches[0]["requirements"] == ["You control a creature"]
        assert database.status()["initialized"] is True

    def test_analyze_deck_returns_partial_combo_recommendations(self, tmp_path):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        snapshot = _write_snapshot(
            tmp_path / "snapshot.json.gz",
            [
                _variant("complete", [("Alpha", 1), ("Beta", 1)]),
                _variant("needs-copy", [("Alpha", 2), ("Beta", 1)]),
                _variant("needs-card", [("Alpha", 1), ("Gamma", 1)]),
                _variant("needs-two-copies", [("Alpha", 1), ("Gamma", 2)]),
                _variant("needs-two", [("Alpha", 1), ("Delta", 1), ("Epsilon", 1)]),
                _variant("unrelated", [("Zeta", 1), ("Eta", 1)]),
            ],
        )
        database.ingest_snapshot(snapshot)

        analysis = database.analyze_deck(
            [{"name": "Alpha", "quantity": 1}, {"name": "Beta", "quantity": 1}],
            include_recommendations=True,
        )

        assert [combo["id"] for combo in analysis["combos"]] == ["complete"]
        assert [combo["id"] for combo in analysis["recommendations"]] == [
            "needs-copy", "needs-card",
        ]
        assert analysis["recommendations"][0]["missing"] == [
            {"name": "Alpha", "quantity": 1},
        ]
        assert analysis["recommendations"][1]["missing"] == [
            {"name": "Gamma", "quantity": 1},
        ]

    def test_recommendations_are_not_capped(self, tmp_path):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        database.ingest_snapshot(_write_snapshot(
            tmp_path / "snapshot.json.gz",
            [_variant(f"combo-{i}", [("Alpha", 1), (f"Missing-{i}", 1)])
             for i in range(25)],
        ))
        analysis = database.analyze_deck(
            [{"name": "Alpha", "quantity": 1}], include_recommendations=True,
        )
        assert len(analysis["recommendations"]) == 25
        assert all(combo["missingCardCount"] == 1 for combo in analysis["recommendations"])

    def test_analyze_deck_filters_recommendations_by_color_identity(self, tmp_path):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        snapshot = _write_snapshot(
            tmp_path / "snapshot.json.gz",
            [
                _variant("blue-combo", [("Alpha", 1), ("BlueCard", 1)], identity="U"),
                _variant("red-combo", [("Alpha", 1), ("RedCard", 1)], identity="UR"),
                _variant("colorless-combo", [("Alpha", 1), ("ArtifactCard", 1)], identity="C"),
            ],
        )
        database.ingest_snapshot(snapshot)

        # Deck with mono-blue color identity should only get blue and colorless recommendations
        analysis = database.analyze_deck(
            [{"name": "Alpha", "quantity": 1}],
            include_recommendations=True,
            allowed_color_identity=["U"],
        )

        rec_ids = [c["id"] for c in analysis["recommendations"]]
        assert "blue-combo" in rec_ids
        assert "colorless-combo" in rec_ids
        assert "red-combo" not in rec_ids

        colorless = database.analyze_deck(
            [{"name": "Alpha", "quantity": 1}],
            include_recommendations=True,
            allowed_color_identity=[],
        )
        assert [combo["id"] for combo in colorless["recommendations"]] == ["colorless-combo"]

        multicolor = database.analyze_deck(
            [{"name": "Alpha", "quantity": 1}],
            include_recommendations=True,
            allowed_color_identity=["U", "R"],
        )
        assert {combo["id"] for combo in multicolor["recommendations"]} == {
            "blue-combo", "red-combo", "colorless-combo",
        }

    def test_snapshot_refresh_reports_added_changed_and_removed_variants(self, tmp_path):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        first = _write_snapshot(
            tmp_path / "first.json.gz",
            [
                _variant("keep", [("Alpha", 1)], produces=("Infinite mana",)),
                _variant("remove", [("Beta", 1)]),
            ],
            version="1.0",
        )
        second = _write_snapshot(
            tmp_path / "second.json.gz",
            [
                _variant("keep", [("Alpha", 1)], produces=("Infinite damage",)),
                _variant("add", [("Gamma", 1)]),
            ],
            version="2.0",
        )

        first_result = database.ingest_snapshot(first)
        second_result = database.ingest_snapshot(second)

        assert (first_result["added"], first_result["changed"], first_result["removed"]) == (
            2,
            0,
            0,
        )
        assert (second_result["added"], second_result["changed"], second_result["removed"]) == (
            1,
            1,
            1,
        )
        assert database.status()["version"] == "2.0"
        assert [combo["id"] for combo in database.matches([{"name": "Alpha"}])] == ["keep"]

    def test_invalid_download_leaves_existing_snapshot_untouched(self, tmp_path, monkeypatch):
        database = CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite")
        snapshot = _write_snapshot(
            tmp_path / "first.json.gz", [_variant("keep", [("Alpha", 1)])]
        )
        database.ingest_snapshot(snapshot)
        client_type = httpx.Client

        def handler(request):
            return httpx.Response(503)

        monkeypatch.setattr(
            spellbook.httpx,
            "Client",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )

        with pytest.raises(httpx.HTTPStatusError):
            database.update()

        assert database.status()["variantCount"] == 1
        assert [combo["id"] for combo in database.matches([{"name": "Alpha"}])] == ["keep"]

    def test_rejects_snapshot_missing_required_metadata_or_arrays(self, tmp_path):
        path = tmp_path / "bad.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as output:
            json.dump({"timestamp": "2025", "version": "1", "variants": []}, output)

        with pytest.raises(ValueError, match="missing its combo arrays"):
            CommanderSpellbookDatabase(tmp_path / "spellbook.sqlite").ingest_snapshot(path)
