# `player-assets` — token art, sleeves, favorite decks

**Path**: `backend/data/player_assets.db` (`DATA_DIR/player_assets.db`,
overridable via `MTG_DATA_DIR`). Owning service: `services/player_assets.py`'s
`PlayerAssetStore`.

**Real user data**, keyed by free-text `player_name` — this app has no auth,
so `player_name` (set on the **Profil** tab) is the only identity a row has.

## Schema

```sql
CREATE TABLE token_images (
    player_name TEXT NOT NULL, token_name TEXT NOT NULL,
    content_type TEXT NOT NULL, data BLOB NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, token_name)
);
CREATE TABLE sleeves (
    player_name TEXT NOT NULL, sleeve_id TEXT NOT NULL, label TEXT NOT NULL,
    content_type TEXT NOT NULL, data BLOB NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, sleeve_id)
);
CREATE TABLE favorite_decks (
    player_name TEXT NOT NULL, deck_id TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (player_name, deck_id)
);
```

## Gotchas

- **No `COLLATE NOCASE` anywhere here** — unlike `cards`/`decks`, a lookup
  must match `player_name` exactly as the player typed it on the Profil tab
  ("Bernd" and "bernd" are different rows). This is the opposite convention
  from the other four stores; don't assume case-insensitivity carries over.
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
python $QUERY sql player-assets "SELECT player_name, token_name, LENGTH(data) AS bytes FROM token_images"
python $QUERY sql player-assets "SELECT player_name, sleeve_id, label FROM sleeves"
python $QUERY sql player-assets "SELECT * FROM favorite_decks WHERE player_name = 'Bernd'"
```
