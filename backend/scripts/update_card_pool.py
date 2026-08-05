#!/usr/bin/env python3
"""Refresh the full-coverage Oracle card pool from Scryfall.

`scripts/import_bulk.py` is the *first-load* tool — its default reuses an
existing dump on disk so a re-run never re-downloads by accident. This is its
maintenance counterpart: run it periodically (a new set released, a Banned
and Restricted announcement landed, …) to pull the *current* Scryfall
`oracle_cards` bulk dump, merge it into the persistent raw store (new Oracle
ids are added, existing ones get their JSON refreshed in place — errata,
new legality, updated rulings-adjacent fields), and reseed the app cache from
it, same as `import_bulk.py --reseed-only` does.

It also flags the two things a human still has to act on by hand, since
neither has a live source of truth in this codebase:

  * **New cards**: printed as a name list so a release can be sanity-checked
    (e.g. "did the new set actually land"), not applied anywhere automatically.
  * **Commander ban-list drift**: `services/commander_legality.py`'s
    `BANNED_COMMANDER_CARDS` is hand-maintained (the per-printing `legalities`
    field is stored in the raw dump but not surfaced anywhere else). This
    script diffs that constant against the freshly downloaded `legalities.
    commander` field and prints any additions/removals — it does not edit the
    source file; update `BANNED_COMMANDER_CARDS` by hand per its own
    docstring, using this output as the changelog.

Usage (from backend/, venv active):
  python scripts/update_card_pool.py [--db PATH] [--dump PATH] [--reuse-dump] [--skip-reseed]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_bulk import _DEFAULT_DUMP, _download_dump, _seed_cache_from_store  # noqa: E402

from mtg_analyzer.services.card_database import DEFAULT_DB_PATH  # noqa: E402
from mtg_analyzer.services.commander_legality import BANNED_COMMANDER_CARDS  # noqa: E402
from mtg_analyzer.services.raw_card_store import RawCardStore  # noqa: E402

#: How many new-card names to print before summarizing the rest — a whole
#: new set is ~250-400 cards, too long to dump in full on every run.
_MAX_NAMES_SHOWN = 40


def _print_name_sample(label: str, names: list[str]) -> None:
    print(f"{label} ({len(names)}):")
    for name in sorted(names)[:_MAX_NAMES_SHOWN]:
        print(f"  + {name}")
    if len(names) > _MAX_NAMES_SHOWN:
        print(f"  ... and {len(names) - _MAX_NAMES_SHOWN} more")


def _diff_ban_list(cards: list[dict]) -> None:
    live_banned = {
        c["name"] for c in cards
        if (c.get("legalities") or {}).get("commander") == "banned"
    }
    newly_banned = sorted(live_banned - BANNED_COMMANDER_CARDS)
    no_longer_banned = sorted(BANNED_COMMANDER_CARDS - live_banned)

    if not newly_banned and not no_longer_banned:
        print("Commander ban list: no drift vs BANNED_COMMANDER_CARDS.")
        return

    print("Commander ban list drift vs BANNED_COMMANDER_CARDS "
          "(services/commander_legality.py) — update that constant by hand:")
    for name in newly_banned:
        print(f"  + now banned on Scryfall, missing from our list: {name}")
    for name in no_longer_banned:
        print(f"  - in our list but no longer banned on Scryfall: {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="target app cache DB")
    parser.add_argument("--dump", type=Path, default=_DEFAULT_DUMP, help="dump download/read location")
    parser.add_argument("--reuse-dump", action="store_true",
                        help="skip the download and diff/reseed from the dump already on disk "
                             "(for offline testing; the whole point of this script is normally "
                             "to fetch a fresh one)")
    parser.add_argument("--skip-reseed", action="store_true",
                        help="update the raw store and print the diff, but don't rebuild the app cache")
    args = parser.parse_args()

    store = RawCardStore()
    before_ids = store.all_oracle_ids()
    print(f"Raw store currently holds {len(before_ids)} cards.")

    if args.reuse_dump:
        if not args.dump.exists():
            sys.exit(f"--reuse-dump but {args.dump} doesn't exist; run once without it first.")
        print(f"Reusing existing dump {args.dump} (no download).")
    else:
        _download_dump(args.dump)

    with args.dump.open("r", encoding="utf-8") as fh:
        cards = json.load(fh)

    stored = store.upsert_many(cards)
    print(f"Merged {stored} cards from the dump into the raw store.")

    after_ids = {c.get("oracle_id") or c.get("id") for c in cards if c.get("oracle_id") or c.get("id")}
    new_ids = after_ids - before_ids
    if new_ids:
        new_names = [c["name"] for c in cards if (c.get("oracle_id") or c.get("id")) in new_ids]
        _print_name_sample("New cards since the last update", new_names)
    else:
        print("No new Oracle ids since the last update (same card pool, possibly refreshed fields).")

    _diff_ban_list(cards)

    if args.skip_reseed:
        store.close()
        print("\n--skip-reseed set: app cache not touched.")
        return

    saved, skipped, failed = _seed_cache_from_store(store, args.db, limit=None)
    store.close()
    print(f"\nReseeded app cache: saved={saved}  skipped(layout)={skipped}  failed={failed}")
    print(f"App cache: {args.db}")
    print("\nNext: re-run `python scripts/coverage_report.py` — the card pool changed, "
          "so parser coverage numbers may have shifted.")


if __name__ == "__main__":
    main()
