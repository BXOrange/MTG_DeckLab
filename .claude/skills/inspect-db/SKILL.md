---
name: inspect-db
description: Read-only inspection of this project's five SQLite stores (card cache, raw Scryfall data, parser-coverage ledger, saved decks, player assets) — look up a cached card, check a card's MODELED/UNMODELED/AUTHORED coverage verdict, browse saved decks, or check a player's uploaded sleeves/token art/favorites. Use when asked to check what's in a database, look something up in the cache/coverage/decks/player-assets store, or debug why a lookup returns nothing. Ships query.py, a read-only SQL runner that resolves the right on-disk path itself.
---

# Inspecting the project's databases

Five independent SQLite stores, five independent jobs. Read **only** the one
reference file that matches the question — they don't share content on
purpose, so opening the other four wastes context for nothing.

| Question is about... | Read | DB file |
| --- | --- | --- |
| A cached card's own data (mana cost, oracle text, whether it's cached at all) | [reference/cards.md](reference/cards.md) | `cache/db/cards.db` |
| The untouched raw Scryfall JSON for a card (fields `Card` doesn't model) | [reference/raw-cards.md](reference/raw-cards.md) | `data/scryfall_raw.db` |
| Parser coverage — a card's MODELED/UNMODELED/AUTHORED verdict, snapshot history | [reference/coverage.md](reference/coverage.md) | `data/coverage.db` |
| Saved decks — entries, commander, author, sleeve_id, is_cube | [reference/decks.md](reference/decks.md) | `data/decks.db` |
| Player-uploaded token art, card-back sleeves, favorite-decks star | [reference/player-assets.md](reference/player-assets.md) | `data/player_assets.db` |

If the question spans two stores (e.g. "which saved decks use a card that's
still UNMODELED"), read both matching reference files — that's the one
legitimate reason to open more than one.

## The tool

```bash
cd backend && source venv/bin/activate     # or use venv/bin/python directly
QUERY=../.claude/skills/inspect-db/scripts/query.py
python $QUERY list                          # every DB: path, exists?, row counts
python $QUERY schema cards                  # CREATE TABLE/INDEX statements
python $QUERY card "Lightning Bolt"         # decoded convenience lookup (cards.db)
python $QUERY coverage "Frodo, Sauron's Bane"  # decoded convenience lookup (coverage.db)
python $QUERY sql decks "SELECT id, name FROM decks ORDER BY created_at DESC LIMIT 10"
```

`sql` opens every connection **read-only** (`file:...?mode=ro`) and refuses
any statement that isn't `SELECT`/`WITH`/`PRAGMA`/`EXPLAIN` before that — this
tool is for looking, never for fixing data. Long `TEXT`/`BLOB` cells are
truncated by default; pass `--full` to see them whole.

## Hard rules

- **Never write through this tool or raw `sqlite3` against these files.**
  Every DB has an app-level owner (`services/*_database.py` /
  `services/coverage_db.py` / `services/player_assets.py`) that keeps
  invariants raw SQL doesn't know about — a unique-name index, a
  content-hash key, preserved-on-omission fields. A write belongs in the
  service layer or not at all.
- `cache/db/cards.db` is **disposable** (re-fetched from Scryfall, wiped on
  any `Card`-model schema drift). The other four are **not** — `decks.db`
  and `player_assets.db` in particular are real user data with no backend
  backup story beyond the filesystem.
- If a lookup by name returns nothing, check the matching reference file's
  gotchas section before assuming the row doesn't exist — case-sensitivity
  and dedup rules differ per store (`cards`/`decks` are case-insensitive on
  name, `player_assets` is not).
