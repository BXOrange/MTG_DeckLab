# `player-assets` — token art, sleeves, favorite decks

**Path**: `backend/data/player_assets.db` (`DATA_DIR/player_assets.db`,
overridable via `MTG_DATA_DIR`). Owning service: `services/player_assets.py`'s
`PlayerAssetStore`.

**Real user data**, owned by an account (`owner_uuid`, PLR-16). Rows written before
accounts existed have `owner_uuid IS NULL` and the old free-text name in `legacy_name`;
the runtime never serves them until `scripts/migrate_legacy_decks.py` assigns them.

## Schema (user_version 1)

```sql
-- token_images / sleeves / favorite_decks share the shape:
CREATE TABLE sleeves (
    id INTEGER PRIMARY KEY, owner_uuid TEXT, legacy_name TEXT,
    sleeve_id TEXT NOT NULL, label TEXT NOT NULL, content_type TEXT NOT NULL,
    data BLOB NOT NULL, updated_at TEXT NOT NULL,
    CHECK (owner_uuid IS NOT NULL OR legacy_name IS NOT NULL)
);
-- unique (owner_uuid, key) where owner_uuid IS NOT NULL; unique (legacy_name, key) where legacy_name IS NOT NULL
-- token_images: token_name instead of sleeve_id/label; favorite_decks: deck_id, no blob
```

## Gotchas

- `legacy_name` matches exactly as typed back then ("Bernd" and "bernd" are different
  rows); `owner_uuid` is the account's `player_uuid` from `accounts.db`.
- `data` is **binary image bytes**, not JSON — never dump it into a text
  table. Use `LENGTH(data) AS bytes` in ad-hoc SQL, or the app's own
  `list_token_images()`/`list_sleeves()` (which already omit the blob and
  are what the Einstellungen UI calls).
- `favorite_decks.deck_id` references `decks.db`'s `id` but there's no
  cross-database foreign key — a favorite can outlive its deck if the deck
  was deleted; the UI is expected to tolerate that, a dangling row here
  isn't itself a bug.

## Examples

```bash
python $QUERY sql player-assets "SELECT owner_uuid, legacy_name, token_name, LENGTH(data) AS bytes FROM token_images"
python $QUERY sql player-assets "SELECT owner_uuid, legacy_name, sleeve_id, label FROM sleeves"
python $QUERY sql player-assets "SELECT * FROM favorite_decks WHERE legacy_name = 'Bernd'"
```
