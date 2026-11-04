# Player profile, uploaded art, saved-deck metadata

Moved out of CLAUDE.md. Load when working on the Profil tab, `services/player_assets.py`, or `Deck.author`/`is_cube`/`sleeve_id`.

**Player-uploaded art** (**Profil** tab): a player can upload art for
tokens that have no real Scryfall art (matched by token name) and a
library of card-back "sleeve" designs, one of which can be picked per
saved deck (`Deck.sleeve_id`). Stored server-side, **owned by the signed-in
account** (`owner_uuid`, PLR-16; never the free-text name) — set on the same
**Profil** tab (`profileView.js`, needs a login) — via `services/player_assets.py` /
`api/player_assets.py` (`/api/me/...`, owner taken from the session; a foreign id is
a 404, anonymous is 401). Nothing is readable by other accounts: the board only loads
the local player's own art (an opponent's hidden-hand backs use *your* sleeve).
Legacy name-keyed rows (`legacy_name`, `owner_uuid IS NULL`) are invisible until
`scripts/migrate_legacy_decks.py` assigns them (opt-in `--assign-assets-by-name`);
`AccountStore.delete_account` removes an account's assets (`bind_account_cleanup`).
Guide: [SERVER_GUIDE.md](SERVER_GUIDE.md) section 4b.
The goldfish/Replay board (`gameBoardView.js` `resolveImageUrl`) renders
a token's uploaded art when present, and falls back to the active
sleeve for a face-down/transformed token with none — real transformed
DFCs keep their genuine Scryfall back-face art, so the sleeve fallback
has no visible effect yet until a face-down permanent state
(morph/manifest, not yet modeled) can reach that branch.

The **Profil** tab also carries two more per-player preferences
alongside the player name and asset uploads: **favorite decks** — a starred subset of the
saved-decks list (`services/player_assets.py`'s third table,
`favorite_decks`, same account-owned storage as sleeves/token art, private to
the owner — a star can't live on a global `Deck`) that `goldfishView.js`'s and
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


**Planned:** local accounts, run modes (LAN default, `--online`, `--localdev`), account-owned
decks and an admin surface are planned, not delivered; everything above remains the current
behaviour until they land. Plan: [15_ACCOUNT_SYSTEM_PLAN.md](../concepts/15_ACCOUNT_SYSTEM_PLAN.md)
(tickets `PLR-9a`–`PLR-9e`).
