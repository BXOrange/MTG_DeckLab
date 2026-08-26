#!/usr/bin/env python3
"""Bulk-import every Oracle card from Scryfall into the persistent raw store,
then seed the app card cache from it.

Reference: docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md, and the plan
"Model all Edge Cases, the whole card database, and all ~30k MTG cards"
(Phase 0a) + the user's "separate engineering database for loading".

Flow (no per-card Scryfall calls, no LLM — one download + local CPU):

  1. Download Scryfall's `oracle_cards` bulk dump *once* (one HTTP request;
     ~one object per Oracle card, ~30k — the app's identity is name-based, so
     `default_cards`'s ~90k printings would be wasted work).
  2. Store the raw JSON in the persistent `RawCardStore` (survives app-cache
     schema wipes — the durable anti-duplicate-work "loading" ledger).
  3. Seed the disposable app cache (`CardDatabase`) from the raw store via the
     existing `card_from_scryfall_data()` converter.

`--reseed-only` skips steps 1-2 and rebuilds the app cache from the raw store
with **no network** — the payoff: once loaded, a `Card`-model change that wipes
the app cache costs a local reseed, never a re-download.

Point it at a scratch app cache with MTG_CACHE_DIR to avoid clobbering a running
dev server. Images stay lazy (populated separately on first view).

Usage (from backend/, venv active):
  python scripts/import_bulk.py [--limit N] [--db PATH] [--dump PATH] [--reseed-only]
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx2 as httpx  # noqa: E402  (after sys.path bootstrap)

from mtg_analyzer.config import DATA_DIR, USER_AGENT  # noqa: E402
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services.raw_card_store import RawCardStore  # noqa: E402
from mtg_analyzer.services.scryfall_client import card_from_scryfall_data  # noqa: E402

_BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"
_DATASET = "oracle_cards"
#: Persistent home for the downloaded dump so a re-run never re-downloads.
_DEFAULT_DUMP = DATA_DIR / "scryfall_oracle_cards.json"

#: Scryfall layouts that carry no real, castable Oracle card — skip them so the
#: coverage denominator stays cards a player can actually play.
_SKIP_LAYOUTS = frozenset(
    {"art_series", "token", "double_faced_token", "emblem", "scheme", "planar", "vanguard"}
)


def _download_dump(dest: Path) -> Path:
    """Resolve the oracle_cards download URI and stream the JSON dump to `dest`.

    Scryfall's bulk-data index dropped the plain-JSON `download_uri` for this
    dataset (as of 2026-08) in favor of a gzip-compressed JSONL stream
    (`jsonl_download_uri`) — one card object per line. Every downstream
    consumer of `dest` (`_load_raw_store`, `update_card_pool.py`) still
    expects a single uncompressed JSON array, so the reassembly happens right
    here rather than pushing the format change out to every caller. Each
    JSONL line is already valid JSON, so reassembly is a string join, not a
    parse+reserialize of ~30k objects.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=headers, timeout=60.0, follow_redirects=True) as client:
        index = client.get(_BULK_INDEX_URL)
        index.raise_for_status()
        entry = next(e for e in index.json()["data"] if e["type"] == _DATASET)
        size_mb = entry.get("compressed_size", entry.get("size", 0)) / 1_000_000

        if "download_uri" in entry:
            uri = entry["download_uri"]
            print(f"Downloading {_DATASET} dump (~{size_mb:.0f} MB) from {uri} ...")
            with client.stream("GET", uri) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):
                        fh.write(chunk)
        else:
            uri = entry["jsonl_download_uri"]
            print(f"Downloading {_DATASET} dump (~{size_mb:.0f} MB compressed, JSONL/gzip) from {uri} ...")
            with tempfile.NamedTemporaryFile(suffix=".jsonl.gz", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                with client.stream("GET", uri) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):
                        tmp.write(chunk)
            try:
                with gzip.open(tmp_path, "rt", encoding="utf-8") as gz, dest.open("w", encoding="utf-8") as out:
                    out.write("[")
                    first = True
                    for line in gz:
                        line = line.strip()
                        if not line:
                            continue
                        if not first:
                            out.write(",")
                        out.write(line)
                        first = False
                    out.write("]")
            finally:
                tmp_path.unlink(missing_ok=True)
    print(f"Saved dump to {dest} ({dest.stat().st_size / 1_000_000:.0f} MB).")
    return dest


def _load_raw_store(dump_path: Path, store: RawCardStore) -> int:
    with dump_path.open("r", encoding="utf-8") as fh:
        cards = json.load(fh)
    stored = store.upsert_many(cards)
    print(f"Stored {stored} raw cards in the persistent raw store.")
    return stored


def _seed_cache_from_store(store: RawCardStore, db_path: Path, limit: int | None) -> tuple[int, int, int]:
    """Convert raw store → app cache. Returns (saved, skipped, failed)."""
    db = CardDatabase(db_path)
    saved = skipped = failed = 0
    started = time.monotonic()
    for data in store.iter_raw():
        if limit is not None and saved >= limit:
            break
        if data.get("layout") in _SKIP_LAYOUTS:
            skipped += 1
            continue
        try:
            db.save_card(card_from_scryfall_data(data))
            saved += 1
        except Exception as exc:  # one bad card must not abort a 30k seed
            failed += 1
            if failed <= 20:
                print(f"  ! skip {data.get('name', '?')!r}: {exc}")
        if saved and saved % 5000 == 0:
            rate = saved / (time.monotonic() - started)
            print(f"  ... {saved} seeded ({rate:.0f}/s)")
    db.close()
    return saved, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="seed at most N cards (quick test)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="target app cache DB")
    parser.add_argument("--dump", type=Path, default=_DEFAULT_DUMP, help="dump download/read location")
    parser.add_argument("--reseed-only", action="store_true",
                        help="skip download; rebuild the app cache from the raw store (no network)")
    args = parser.parse_args()

    store = RawCardStore()

    if not args.reseed_only:
        if args.dump.exists():
            print(f"Using existing dump {args.dump} (delete it to force a re-download).")
        else:
            _download_dump(args.dump)
        _load_raw_store(args.dump, store)
    else:
        if store.count() == 0:
            sys.exit("--reseed-only but the raw store is empty; run once without it first.")
        print(f"Reseeding from raw store ({store.count()} raw cards) — no network.")

    saved, skipped, failed = _seed_cache_from_store(store, args.db, args.limit)
    store.close()
    print(f"\nDone. seeded={saved}  skipped(layout)={skipped}  failed={failed}")
    print(f"App cache: {args.db}")


if __name__ == "__main__":
    main()
