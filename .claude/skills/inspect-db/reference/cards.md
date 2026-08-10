# `cards` — the card cache

**Path**: `backend/cache/db/cards.db` (`CACHE_DIR/db/cards.db`, overridable via
`MTG_CACHE_DIR`). Owning service: `services/card_database.py`'s `CardDatabase`.

**Disposable.** Lazily populated from Scryfall; `services/schema_version.py`
wipes it on any `Card`-model schema drift, and it re-populates lazily from
the network (or `scripts/import_bulk.py` for the full ~34k-card bulk load).
Never treat a row here as a source of truth to hand-edit — if a card's stored
data is wrong, the fix is in `models/card.py`/`services/scryfall_client.py`,
not the row.

## Schema

```sql
CREATE TABLE cards (
    id TEXT PRIMARY KEY,              -- a Scryfall id (one representative printing)
    name TEXT NOT NULL,
    flavor_name TEXT NOT NULL DEFAULT '',  -- blank except Secret Lair/UB promos
    data TEXT NOT NULL                -- JSON: Card.to_dict()
);
CREATE UNIQUE INDEX idx_cards_name ON cards (name COLLATE NOCASE);
CREATE INDEX idx_cards_flavor_name ON cards (flavor_name COLLATE NOCASE);
```

`name` is **unique** (case-insensitive) — one row per Oracle card name, not
per printing. `data` is the full `Card.to_dict()` blob: `mana_cost_string`,
`converted_mana_cost`, `type_line`, `oracle_text`, `keywords`, `power`/
`toughness`/`loyalty`/`defense`, `set_code`, `rarity`, `layout`, plus an
entire parallel `back_*` group for a DFC's back face. See `models/card.py`'s
`to_dict` for the exhaustive field list.

## Gotchas

- Lookup by name is case-insensitive (`get_card`/the unique index both use
  `COLLATE NOCASE`) — a "not found" is a real cache miss, not a casing bug.
- A card that exists in `raw-cards` (see [raw-cards.md](raw-cards.md)) but
  not here just hasn't been converted into a `Card` yet (lazy — happens on
  first request). It being missing from *both* means it was never fetched.
- `mana_cost` (a dict) isn't stored under that key in `data` — only the
  pre-rendered `mana_cost_string`.

## Examples

```bash
python $QUERY card "Lightning Bolt"                 # decoded, key fields only
python $QUERY card "Lightning Bolt" --full           # entire JSON blob
python $QUERY sql cards "SELECT name FROM cards WHERE name LIKE '%Bolt%'"
python $QUERY sql cards "SELECT COUNT(*) AS n FROM cards WHERE flavor_name != ''"
```
