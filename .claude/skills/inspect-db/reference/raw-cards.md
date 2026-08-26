# `raw-cards` — untouched Scryfall JSON

**Path**: `backend/data/scryfall_raw.db` (`DATA_DIR/scryfall_raw.db`,
overridable via `MTG_DATA_DIR`). Owning service: `services/raw_card_store.py`'s
`RawCardStore`.

**Persistent, not disposable** — unlike `cards.db` (see [cards.md](cards.md)),
this survives a `Card`-model schema change on purpose: it's the raw material
`scripts/import_bulk.py`/`update_card_pool.py` re-derive `Card` rows from, so
a schema fix doesn't force a full network re-download of ~34k cards.

## Schema

```sql
CREATE TABLE raw_cards (
    oracle_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    layout     TEXT NOT NULL DEFAULT '',
    json       TEXT NOT NULL,        -- the untouched Scryfall API object
    fetched_at TEXT NOT NULL
);
CREATE INDEX idx_raw_cards_name ON raw_cards (name COLLATE NOCASE);
```

Keyed by **Oracle id**, not the printing id `cards.db` uses — this is the
one card-shaped store keyed that way.

## When to reach for this instead of `cards`

`json` is the full Scryfall object — every field, including ones `Card`
doesn't model at all (full `legalities` per format, `all_parts`, every
printing's own `set`/`collector_number`, `prices`, layout metadata for
rare card shapes). If a question is "what does Scryfall actually say about
X" rather than "what does the engine see for X", this is the store, not
`cards`.

## Gotchas

- `json` is a raw string — decode it yourself (`json.loads`) when reading via
  `sql`; there's no decoded convenience command for this store (the schema is
  Scryfall's, not this app's, so there's nothing stable to special-case).
- `all_oracle_ids()` (Python API, not exposed via `query.py`) is how
  `import_bulk.py` decides what still needs downloading — an id present here
  is considered "already fetched" regardless of whether it made it into
  `cards.db` yet.

## Examples

```bash
python $QUERY sql raw-cards "SELECT name, layout FROM raw_cards WHERE layout != '' LIMIT 20"
python $QUERY sql raw-cards "SELECT json FROM raw_cards WHERE name = 'Chrome Mox' COLLATE NOCASE" --full
```
