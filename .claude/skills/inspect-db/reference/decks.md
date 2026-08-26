# `decks` — saved decks

**Path**: `backend/data/decks.db` (`DATA_DIR/decks.db`, overridable via
`MTG_DATA_DIR`). Owning service: `services/deck_database.py`'s
`DeckDatabase`.

**Real user data — not cache.** Nothing regenerates a saved deck; back this
file up if you care about what's in it, unlike `cards.db`
([cards.md](cards.md)), which is throwaway by design.

## Schema

```sql
CREATE TABLE decks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL     -- JSON: Deck.to_dict()
);
CREATE INDEX idx_decks_created_at ON decks (created_at);
```

`data` holds everything a `Deck` carries: card entries, commander(s),
`author`, `sleeve_id`, `is_cube`. See `models/deck.py`'s `to_dict` for the
exhaustive field list.

## Gotchas

- **No uniqueness on `name`** — two saved decks can share a display name;
  always key on `id` when the question is "which exact deck".
- **Preserved-on-omission is an app-layer behaviour, not a DB one.**
  `api/saved_decks.py`'s `save_deck` keeps the existing `author`/`sleeve_id`
  when a re-save omits them — but that logic lives in the API handler, not
  here. A row you read via raw SQL is simply whatever was last written; it
  won't show you the merge behaviour.
- `is_cube` decks skip Commander legality/structure checks entirely (see
  `CLAUDE.md`'s "Als Cube behandeln") — don't read a cube's apparent
  singleton/100-card violations as bugs.

## Examples

```bash
python $QUERY sql decks "SELECT id, name, created_at FROM decks ORDER BY created_at DESC LIMIT 10"
python $QUERY sql decks "SELECT id, name FROM decks WHERE data LIKE '%\"is_cube\": true%'"
```
