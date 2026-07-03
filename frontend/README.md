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
- **Spielfläche**: a static play-area layout (battlefield, hand,
  library, graveyard, exile, command zone, life total, stack) that
  builds a shuffled opening hand from the imported deck. Cards show
  their real artwork, fetched from Scryfall's public, CORS-enabled
  `/cards/collection` API (`src/js/cardImages.js`) — see a card by
  name, no card database needed for this part. While a lookup is
  pending or a name isn't found, cards fall back to a plain text box.
  Draw/mulligan/move-to-battlefield are local-only mock actions
  (`src/js/boardEngine.js`) with no rules enforcement — there's no real
  game engine or server yet (see `docs/02_MVP_USECASES_REVISED.md`
  UC3). The opponent zones are placeholders until a second deck/session
  can be loaded.

## Structure

```
index.html
src/
  styles/main.css
  js/
    app.js            tab wiring, entry point
    state.js           tiny pub/sub store shared by both views
    parser.js           per-section decklist parsing + structural validation
    cardImages.js        Scryfall artwork lookup (batched, cached)
    deckImportView.js   "Deck importieren" tab (Commander/Mainboard/Sideboard)
    boardEngine.js       mock game state transitions (shuffle/draw/mulligan)
    boardView.js          "Spielfläche" tab, renders card art via cardImages.js
```

## Next steps

Once the backend has a `DecklisteParser`/card database and a real
game engine (see `docs/IMPLEMENTATION_GUIDE.md` Phase 1–3), swap
`parser.js`'s client-side parsing for a call to the deck-validation
API, and `boardEngine.js`'s local mock for real server/WebSocket
game-state updates — the view layer (`deckImportView.js`,
`boardView.js`) was kept deliberately dumb (render what's in `state.js`)
so that swap doesn't require rewriting the UI.
