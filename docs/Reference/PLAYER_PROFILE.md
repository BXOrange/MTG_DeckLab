# Player profile, uploaded art, saved-deck metadata

Moved out of CLAUDE.md. Load when working on the Profil tab, `services/player_assets.py`, or `Deck.author`/`is_cube`/`sleeve_id`.

**Player-uploaded art** (**Profil** tab): a player can upload art for
tokens that have no real Scryfall art (matched by token name) and a
library of card-back "sleeve" designs, one of which can be picked per
saved deck (`Deck.sleeve_id`). Stored server-side keyed by the free-text
player name (this app has no auth) — set on the same **Profil** tab
(`profileView.js`), read via `getSettings().playerName` — via `services/
player_assets.py` / `api/player_assets.py` rather than client-side,
specifically so a shared backend can serve them to an opponent too at a
multiplayer table.
The goldfish/Replay board (`gameBoardView.js` `resolveImageUrl`) renders
a token's uploaded art when present, and falls back to the active
sleeve for a face-down/transformed token with none — real transformed
DFCs keep their genuine Scryfall back-face art, so the sleeve fallback
has no visible effect yet until a face-down permanent state
(morph/manifest, not yet modeled) can reach that branch.

The **Profil** tab also carries two more per-player preferences
alongside the player name and asset uploads: **favorite decks** — a starred subset of the
saved-decks list (`services/player_assets.py`'s third table,
`favorite_decks`, same `player_name`-keyed storage as sleeves/token
art — decks aren't owned in this single shared `DeckDatabase`, so the
star can't live on `Deck` itself) that `goldfishView.js`'s and
`multiplayerView.js`'s deck pickers list first; and **multiplayer
default settings** (format, mulligan style, takebacks, RULE 103.1/103.2
randomization) — purely client-side cookies (`settings.js`, same
convention as the auto-pass toggles on the same tab), applied once by
`multiplayerView.js`'s `createGame()` via the same host-only
`setMultiplayerOptions` call the table's own option rows use, right
after a table is created.

A saved `Deck` also carries a free-text, optional `author` field (a
descriptive credit, not an owner/auth concept — this app still has no user
accounts) — set on the deck-import/edit tab and shown read-only in the
saved-decks list, preserved-on-omission the same way `sleeve_id` is
(`api/saved_decks.py`'s `save_deck`: a re-save that doesn't send `author`
keeps the existing value). The saved-decks list also gained client-side
color-identity/legality filters, the same checkbox-fieldset pattern the
card cache view uses (`savedDecksView.js`/`cachedCardsView.js`).

A saved `Deck` can also be flagged `is_cube` (`models/deck.py`) — a card
pool (e.g. a curated "cEDH staples" reference list) rather than a real,
legal Commander deck. When set, `services/deck_validation.py` skips both
the structural Commander checks (100-card total, singleton,
`parser/deckliste_parser.py`) and the semantic ones (ban list, color
identity, Partner — `services/commander_legality.py`) entirely, rather
than reporting the pool's inherent "violations" as errors — same
preserved-on-omission save semantics as `author`/`sleeve_id`. Set via a
"Als Cube behandeln" checkbox on the deck-import/edit tab
(`deckImportView.js`); the saved-decks list shows a 🧊 badge instead of
the usual legality check (`savedDecksView.js`) and gained a matching
"Art" (Deck/Cube) filter, same checkbox-fieldset pattern as color/legality.
