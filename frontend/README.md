# Frontend (Browser Client)

Plain HTML/CSS/JS (ES modules), no build step, no dependencies. This
machine has no Node/npm installed, so this deliberately avoids a
bundler — it can be extended to React/Vite later (see
[docs/04_SERVER_CLIENT_ARCHITECTURE.md](../docs/04_SERVER_CLIENT_ARCHITECTURE.md))
without changing how it's served in the meantime.

## Run

From the repo root: `./start.sh` (macOS/Linux) or `start.bat` (Windows)
— see [../README.md](../README.md). Or standalone, without the root
scripts:

```bash
cd frontend
python3 -m http.server 8765
```

Open http://localhost:8765 in a browser.

## What's here (Step 1)

- **Deck importieren**: three separate input sections — Commander,
  Mainboard, Sideboard. Which section a card is typed into is what
  determines its assignment (no inline header/tag parsing needed).
  Each line is "4x Card" or "1 Card", with trailing set info like
  "(LTR) 123" stripped — see `src/js/parser.js`. Gives a structural
  Commander legality check (100 cards, singleton, exactly one
  commander). There's no card database yet, so this can't validate
  color identity, the ban list, or that a card name actually exists.
- **Goldfisch**: solo play against the real backend rules engine
  (`src/js/goldfishView.js` → `POST /api/game/*`). Pick a saved deck
  from a dropdown (only legal decks may start), then step through the
  turn — play lands, tap mana, cast, attack — from the server's
  `legal_actions`, with rewind/restart. Replaced the old local,
  rule-less mock board (`boardEngine.js`/`boardView.js`, now deleted).
- **Multiplayer**: a stub tab (`src/js/multiplayerView.js`) — the
  backend route returns 501 until the interactive priority loop exists.

## Structure

```text
index.html
src/
  styles/main.css
  js/
    app.js               tab wiring, entry point
    state.js             tiny pub/sub store (parsed deck + image cache)
    parser.js            per-section decklist parsing (local pre-check)
    cardImages.js        card artwork lookup via the backend (batched, cached)
    deckImportView.js    "Deck editieren" tab (Commander/Mainboard/Sideboard)
    savedDecksView.js    "Decks verwalten" tab (list/load/delete, legality)
    goldfishView.js      "Goldfisch" tab, server-driven solo play
    multiplayerView.js   "Multiplayer" tab (stub)
    cachedCardsView.js   "Karten-Cache" tab
    api.js               backend HTTP client (/api/decks, /api/cards, /api/game)
    gameSocket.js        WebSocket client (kept for future multiplayer)
```

See `ToDo_Frontend.md` / `Done_Frontend.md` for feature status.
