# DeckLab: Card Graphics & Lazy Loading

This document describes how card art actually flows through the app today —
Scryfall bulk/lazy import → local server-side cache → backend-served images →
frontend rendering — plus the player-uploaded token art and card-back sleeve
system layered on top of it. It replaces an earlier version of this file
that designed a browser calling `https://api.scryfall.com/cards/named` and
`cards.scryfall.io` image URLs *directly* from client-side React components,
with per-card SQL tables and a phased "Week 1-2" build plan. None of that
survived contact with the real project: there is no React, the browser never
talks to Scryfall, and the card cache is one JSON-blob-per-row SQLite table
(`services/card_database.py`), not a hand-maintained relational schema. See
[`03_ARCHITECTURE_AND_BUILDPLAN.md`](03_ARCHITECTURE_AND_BUILDPLAN.md) for
the system overview this document assumes, and
[`04_SERVER_CLIENT_ARCHITECTURE.md`](04_SERVER_CLIENT_ARCHITECTURE.md) for
the API layer in general.

---

# PART 1: THE REAL IMAGE PIPELINE

**The browser never calls Scryfall.** Every card image a player sees is
served by the backend itself, from a local cache, at
`GET /api/cards/{card_id}/image?size=<small|normal|large|png>&face=<front|back>`
(`backend/mtg_analyzer/api/images.py`). That handler:

1. Looks up the card by its Scryfall id in `CardDatabase`
   (`services/card_database.py`) — a card must already be cached (resolved
   once via `POST /api/cards/resolve` or `GET /api/cards/search`) since
   that's where its Scryfall image *URLs* come from; this endpoint itself
   never talks to Scryfall's card-data API.
2. Reads the URL for the requested size/face off the `Card` model
   (`image_uri_small/normal/large/png`, or the `back_image_uri_*` sibling
   for `face=back` — double-faced cards share one Scryfall id across both
   faces, so the back face gets its own field rather than its own row).
3. Hands that URL to `ImageCache.get_or_fetch` (`services/image_cache.py`),
   which downloads the bytes from `cards.scryfall.io` **once**, writes them
   to `cache/images/<card_id>/<size>[_back].<jpg|png>`, and serves that file
   on every subsequent request — for any browser, not just the one that
   triggered the first fetch. The link between a card and its cached image
   is implicit: both `CardDatabase` and `ImageCache` are keyed by the same
   Scryfall `id`, so no path is ever stored in the database row.
4. Returns a `FileResponse` over the local file.

So the real flow for a never-before-seen card is: frontend resolves the
name → backend's `LazyCardLoader` (`services/lazy_card_loader.py`) fetches
card *data* from Scryfall's `/cards/collection` (or `/cards/named` for a
single lookup/flavor-name fallback) and stores it via `CardDatabase.save_card`
→ frontend asks for an *image* by the now-known card id → the backend fetches
the image bytes once via `ImageCache` and caches them to disk. Every later
request for that card, data or image, by anyone, is served purely from local
SQLite/disk — no Scryfall round trip at all. This is the load-bearing
difference from the old design: that version had the *browser* hold a
`card.image_uris.normal` URL and fetch `cards.scryfall.io` straight from
`<img src>`, so every viewer re-fetched from Scryfall on every session (mitigated
there only by the browser's own HTTP cache) and the server never had a
canonical copy to reuse across users or serve when Scryfall is unreachable.

Both stores are disposable and gitignored (`backend/cache/`, see
`CardDatabase`'s own docstring) — deleting either just means the next lookup
re-fetches from Scryfall (data) or re-downloads from `cards.scryfall.io`
(images). Export/import for sharing a populated cache between machines is
`docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md`; `backend/scripts/
import_bulk.py` is the maintenance script that seeds the *whole* ~35k-card
Oracle pool in one bulk download (Scryfall's `oracle_cards` dataset) plus a
persistent `RawCardStore` so a later `Card`-model change can reseed the app
cache from disk with **no network at all** (`--reseed-only`) — this is what
`backend/conftest.py`'s isolated test cache and `--full-cache` tests rely on,
not something a normal dev session needs to run; ordinary gameplay populates
the cache incrementally, one resolved deck at a time, via `LazyCardLoader`.
Card images stay lazy either way — the bulk importer only ever touches card
*data*, never images (see its own docstring).

---

# PART 2: CACHE-PRIMARY VS. SCRYFALL-PRIMARY

An already-cached card is normally served **as-is**, even if it looks
incomplete (missing mana-cost/image data, or a pre-fix reminder-text
artifact — `lazy_card_loader.py`'s `_is_fresh`) — this is the
`SCRYFALL_PRIMARY=False` default ("cache-primary"). The reasoning, from
`CLAUDE.md`'s "Scryfall loading policy": **an ordinary deck browse must
never make a surprise Scryfall call**, since that could hit Scryfall's rate
limit or fail outright when offline. `SCRYFALL_PRIMARY=True`
(`MTG_SCRYFALL_PRIMARY` env var, or `./start.sh --scryfall-primary`)
restores the project's original "always prefer fresh Scryfall data"
behavior, refetching a stale row. Either way, a name that has *never* been
cached is always fetched once — there's no cached value to prefer over. This
policy lives in `LazyCardLoader.__init__`'s `scryfall_primary` flag
(`config.SCRYFALL_PRIMARY`) and only governs *data* freshness; the image
cache (`ImageCache`) has no equivalent staleness concept at all — an image,
once downloaded, is served forever until the cache directory is deleted by
hand.

This ties directly into `CLAUDE.md`'s "Starting is offline-safe" guarantee:
nothing the app does *at startup* reaches the network. A deck import or a
goldfish game against never-before-seen cards still needs one Scryfall round
trip the first time those names are seen — that's unavoidable lazy loading,
not a startup call — but every already-known card, and the whole app's own
boot sequence, works with zero connectivity.

---

# PART 3: FRONTEND RENDERING & LAZY LOADING

There is no client-side image-loading framework, `IntersectionObserver`, or
prefetch machinery — the real mechanism is the plain HTML attribute
`loading="lazy"` on every `<img>` tag that renders a card, letting the
browser itself defer offscreen images. Every card-rendering call site does
this the same way: `frontend/src/js/cardTile.js`'s `renderCardTile` (`<img
src="${cardImageUrl(card.id, 'normal')}" ... loading="lazy" />`),
`cardHoverDetail.js`'s tooltip image, and `gameBoardView.js`'s `objCard`
(battlefield/hand tiles). `cardImageUrl(cardId, size, face)`
(`frontend/src/js/api.js`) just builds the `GET /api/cards/{id}/image` URL
described in Part 1 — no separate frontend image cache or blob store; the
browser's own HTTP cache plus the backend's on-disk `ImageCache` do all the
real caching.

What *is* cached client-side is card **data**, not image bytes:
`cardImages.js` keeps an in-memory `Map` from lowercased card name to
`{small, normal, backSmall, backNormal, card}`, populated by
`resolveCardImages(names)` (→ `POST /api/cards/resolve`, batching a whole
decklist in one round trip) so a page that re-renders the same deck
repeatedly never re-issues the resolve call. A double-faced permanent that
has actually transformed mid-game is indexed under **both** its front and
back name in this cache, since `GameObject.to_dict()`'s `name` field becomes
the back face's name after a flip. `preloadCardImages` goes one step further
for the goldfish "loading" screen: after resolving names, it warms the
browser's own image cache by constructing `new Image()` objects for every
card (and DFC back face) up front, so the board's first render shows
already-loaded art instead of images popping in one at a time.

**Card display sizing** is real but simple, not the tiered
small/medium/large/png scheme the old doc invented: `cardImageUrl`'s `size`
parameter is one of the four Scryfall sizes the backend/`ImageCache`
actually stores (`small`, `normal`, `large`, `png`), and in practice the app
only ever requests two of them — `small` for compact contexts (battlefield/
hand tiles in `gameBoardView.js`, the hover tooltip in
`cardHoverDetail.js`) and `normal` for the larger card-tile views
(`cardTile.js`'s deck-import/card-cache tiles). Actual on-screen pixel
dimensions are governed by CSS, not a size baked into the JS — this document
doesn't restate CSS values that can drift independently of this file.

---

# PART 4: PLAYER-UPLOADED ART (TOKEN ART & SLEEVES)

This is the part the old plan has no concept of at all: a player can upload
their own art for two things, from the **Profil** tab
(`frontend/src/js/profileView.js`), stored server-side keyed by their
free-text player name (`services/player_assets.py`'s `PlayerAssetStore`,
three SQLite tables — `token_images`, `sleeves`, `favorite_decks` — image
bytes stored directly as a BLOB column, unlike the Scryfall cache, since
these are small user uploads with no upstream to re-fetch). Keying by
`player_name` rather than a browser session or cookie is deliberate: this
app has no accounts, and a shared backend needs to serve an opponent's
uploaded art too at a multiplayer table, not just the uploader's own client.

- **Token art**, matched by exact token name (`POST /api/players/{name}/
  token-images`, read via `GET .../token-images/image?token_name=`) — for
  tokens an effect synthesizes inline ("create a 1/1 white Soldier creature
  token") that have no ability of their own and so never resolve through the
  ordinary card-data pipeline. A special key, `GENERIC_TOKEN_KEY`
  (`"__generic__"`, `api.js`), lets a player set one fallback image used for
  *any* token with no specific upload of its own.
- **Sleeves** — a generic card-back design (`POST /api/players/{name}/
  sleeves`, labeled, server-assigned id), selectable per saved deck via
  `Deck.sleeve_id`. Used as the board's "back of card" fallback for a
  face-down object with no real art of its own — RULE 701.20a exile-face-
  down, and RULE 708.2 morph/disguise/manifest/cloak permanents (a 2/2 with
  no printed identity at all). Real transforming DFCs are unaffected: they
  have genuine Scryfall back-face art (`back_image_uri_*`, Part 1) and never
  reach the sleeve fallback.

Uploads are validated server-side against a small image-content-type
allow-list and a 5 MB size cap (`api/player_assets.py`'s
`_read_validated_image`) before being accepted.

**Default art for a vanilla token** — the case a player upload hasn't
covered — comes from a third, much larger dataset that ships *with the
repository* rather than being cached or uploaded: `TokenArtLibrary`
(`services/token_database.py`, built from Scryfall's token sheets into
`data/token_art.json` by `scripts/build_token_art_library.py`). It's keyed
by the exact `(name, power, toughness, colors)` tuple — necessary because
Magic reprints the same token name at different stat lines across sets (a
"Shapeshifter" token exists as a 1/1, a 2/2, and others). `synthesize_token_
card` (called whenever an effect creates an ad hoc token with no catalogue
entry) looks itself up here and, on a hit, stamps the token's `Card` with
that printing's real Scryfall id and image URIs — so from that point on a
vanilla token's art flows through the *exact same* `CardDatabase`/
`ImageCache`/`GET /api/cards/{id}/image` path as any real card (Part 1), not
through the player-asset system at all. A miss just leaves the token
imageless, same as before this library existed — purely cosmetic, never a
hard failure.

**Real precedence order**, read directly from `gameBoardView.js`'s
`resolveImageUrl(o, imageCache)` (the function every battlefield/hand tile
calls to pick an object's art):

1. A card exiled face down (RULE 701.20a) or any other face-down permanent
   (RULE 708.2) → the player's selected sleeve, or nothing.
2. A token: an *id*-keyed match in the caller's local `imageCache` (per-
   variant, seeded by `preloadDeckTokens` from the deck's producible-token
   list — this is where `TokenArtLibrary`-sourced real art or a curated
   `data/tokens.json` entry's art is found).
3. Any object (token or not): a *name*-keyed match in the same
   `imageCache` — the deck-resolve cache from Part 3, covering real cards
   and the fallback path for tokens the id-lookup missed.
4. A token still unresolved: the player's own uploaded art for that exact
   token name (`tokenImages[name]`, Part 4's `PlayerAssetStore` art).
5. A token showing its back face with none of the above: the player's
   sleeve (a face-down/transformed token copy has no real "back" art of its
   own).
6. A token with nothing at all: the player's generic-token upload
   (`tokenImages[GENERIC_TOKEN_KEY]`), or null.
7. Any non-token object with a `card_id`: built straight from
   `cardImageUrl(card_id, 'small', face)` — the ordinary backend-served path
   from Part 1. This is also the fallback for objects added directly in
   Replay/Puzzle mode, which were never resolved into a deck's `imageCache`.

So the effective order for a token is: **real printed/library art (via the
id-keyed cache) → the deck-resolve name cache → the player's own upload →
sleeve (back only) → generic upload → nothing**; for anything else it's
simply "the resolved deck cache, else the backend image endpoint directly."

---

# PART 5: WHAT CHANGED FROM THE OLD PLAN

**Dropped:**

- The browser calling `api.scryfall.com`/`cards.scryfall.io` directly from
  `<img>` tags or a `fetch`-based React component — replaced end to end by
  the backend-owned `CardDatabase`/`ImageCache` pipeline in Part 1. No
  frontend code in this project imports or references a Scryfall host at
  all.
- The invented multi-table relational schema (`cards`, `decks`,
  `deck_cards` with per-field SQL columns) — the real `CardDatabase` is one
  table storing each card's `to_dict()` as a JSON blob, so the stored shape
  tracks the `Card` model automatically as fields are added (see that
  service's own module docstring).
- The imagined tiered small/medium/large pixel scheme for hand/battlefield/
  expanded views, and the `React.CardImage` component sketch — this project
  has no React and no such fixed tiering; see Part 3 for what's real.
- The "periodic 30-day Scryfall refresh" scheduled job — no such job exists;
  freshness is instead governed by the request-time `SCRYFALL_PRIMARY`
  policy in Part 2.

**Added, unanticipated by the old plan:**

- The entire player-uploaded-art system (Part 4): per-player token art and
  sleeves, keyed by player name so a shared backend can serve them to an
  opponent, plus the committed `TokenArtLibrary` covering vanilla tokens the
  curated `data/tokens.json` catalogue never touches.
- A durable `RawCardStore` behind the disposable `CardDatabase`, so a
  card-model schema change costs a local reseed instead of a re-download
  (Part 1).
- The offline-safe startup guarantee (Part 2) — nothing about launching the
  app itself depends on network access; only resolving a name the cache has
  never seen does.
