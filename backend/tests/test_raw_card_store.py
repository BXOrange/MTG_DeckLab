"""Tests for the persistent raw-Scryfall card store.

Reference: services/raw_card_store.py — the durable "loading" ledger that keeps
the bulk 30k download safe from app-cache schema wipes.
"""

from mtg_analyzer.services.raw_card_store import RawCardStore


def _raw(oracle_id="oid-1", name="Lightning Bolt", layout="normal", **extra):
    return {"oracle_id": oracle_id, "name": name, "layout": layout, **extra}


class TestUpsertAndIterate:
    def test_stores_and_yields_raw_objects(self):
        store = RawCardStore(":memory:")
        store.upsert_many([_raw(), _raw(oracle_id="oid-2", name="Counterspell")])
        assert store.count() == 2
        names = {r["name"] for r in store.iter_raw()}
        assert names == {"Lightning Bolt", "Counterspell"}

    def test_upsert_replaces_by_oracle_id(self):
        store = RawCardStore(":memory:")
        store.upsert_many([_raw(oracle_text="old")])
        store.upsert_many([_raw(oracle_text="new")])
        assert store.count() == 1
        assert next(store.iter_raw())["oracle_text"] == "new"

    def test_falls_back_to_printing_id_when_no_oracle_id(self):
        store = RawCardStore(":memory:")
        stored = store.upsert_many([{"id": "printing-1", "name": "Token", "layout": "token"}])
        assert stored == 1
        assert store.count() == 1

    def test_row_without_any_id_is_skipped_not_crashed(self):
        store = RawCardStore(":memory:")
        stored = store.upsert_many([{"name": "No IDs here"}])
        assert stored == 0
        assert store.count() == 0

    def test_iterates_name_ordered(self):
        store = RawCardStore(":memory:")
        store.upsert_many([_raw(oracle_id="b", name="Zephyr"), _raw(oracle_id="a", name="Abrupt")])
        assert [r["name"] for r in store.iter_raw()] == ["Abrupt", "Zephyr"]

    def test_raw_json_roundtrips_full_object(self):
        store = RawCardStore(":memory:")
        original = _raw(mana_cost="{R}", cmc=1, colors=["R"])
        store.upsert_many([original])
        assert next(store.iter_raw()) == original
