# Card Cache: Layout, Export & Import

Reference implementation: `backend/mtg_analyzer/services/card_database.py`,
`image_cache.py`. See also docs/concepts/06_CARD_GRAPHICS_AND_LAZY_LOADING.md for
the lazy-loading design this cache implements.

**Not to be confused with `backend/data/`** (saved decks,
`services/deck_database.py`): that directory sits right next to this
one but holds real user data with no upstream source to regenerate it
from. Everything below — "always safe to delete", export/import as a
convenience rather than a backup — applies only to `backend/cache/`.

## What's in the cache

Everything lives under `backend/cache/`, which is gitignored — it's a
disposable local cache, never committed:

```
backend/cache/
├── db/
│   └── cards.db          # SQLite: one row per card (id, name, JSON blob)
└── images/
    └── <scryfall_id>/
        ├── small.jpg
        ├── normal.jpg
        ├── large.jpg
        └── png.png
```

`CACHE_ROOT` in `card_database.py` is the single source of truth for
this path; `image_cache.py` derives its own directory from it so the
two never drift apart.

### How the DB and images link up

There's no `image_path` column in the database. The link is implicit:
a card's Scryfall `id` (the DB's primary key) is also the name of its
image subdirectory. Given a card row with `id =
"7673784e-db4b-43a1-8d55-1bb9fc1e284f"`, its cached normal-size image
is always at `cache/images/7673784e-db4b-43a1-8d55-1bb9fc1e284f/normal.jpg`
— computed from the id, never stored. This keeps the database
portable (no machine-specific paths baked into the JSON blob) and lets
you delete the image cache without touching the database, or vice
versa.

Both halves populate lazily and independently:
- The DB fills in as `GET /api/cards/search?name=...` resolves cards.
- The image directory fills in as `GET /api/cards/{id}/image` is hit
  (which requires the card to already be in the DB, since that's where
  its Scryfall image URLs come from).

Because of this, the cache is entirely regenerable — deleting all of
`backend/cache/` is always safe; the next request just re-fetches from
Scryfall and rebuilds it, slower.

## Why export/import it

- Warm a fresh checkout or a new dev machine instantly instead of
  waiting for lazy fetches to happen one card at a time.
- Share a cache after loading a large decklist so a teammate doesn't
  re-fetch the same few hundred cards.
- Snapshot/back up before an experiment that might otherwise leave the
  cache in a weird state.

## Export

Stop the server first — `cards.db` is a live SQLite file, and copying
it out from under an active writer risks grabbing a half-committed
page.

```bash
cd backend
tar -czf card-cache.tar.gz cache/
```

If you can't stop the server (e.g. exporting from a long-running dev
instance), use SQLite's own online backup instead of copying the file
directly — it's safe to run against a database that's being written to
concurrently:

```bash
sqlite3 backend/cache/db/cards.db ".backup /tmp/cards-backup.db"
tar -czf card-cache.tar.gz -C backend cache/images -C /tmp cards-backup.db
```

## Import

Extract into a fresh checkout's `backend/` directory — this recreates
`backend/cache/` in place, so just start the server normally afterward:

```bash
cd backend
tar -xzf /path/to/card-cache.tar.gz
```

## Verify it worked

Look up a card you know is in the imported cache and confirm the
response is effectively instant (no Scryfall round trip):

```bash
time curl -s "http://127.0.0.1:8000/api/cards/search?name=Lightning%20Bolt" > /dev/null
```

A cache hit responds in single-digit milliseconds; a cold fetch from
Scryfall takes closer to 100-300ms.
