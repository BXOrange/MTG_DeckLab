# Frontend (Browser Client)

Plain HTML/CSS/JS (ES modules), no build step, no dependencies. This
machine has no Node/npm installed, so this deliberately avoids a
bundler — it can be extended to React/Vite later (see
[docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md](../docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md))
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

## What's here

A collapsible sidebar (`app.js`) switches between these tabs — see
[`../user-docs/`](../user-docs/) for a player-facing walkthrough of each,
in English and German:

- **Deck editieren**: three input sections — Commander, Mainboard,
  Sideboard (which section a card is typed into determines its
  assignment). Each line is "4x Card" or "1 Card", with trailing set info
  like "(LTR) 123" stripped (`src/js/parser.js`, a local pre-check);
  `POST /api/decks` is the authoritative follow-up, giving real Commander
  legality (color identity, ban list, partner) via the backend card
  database — see `Done_Frontend.md` "Backend integration".
- **Decks verwalten**: saved decks (`savedDecksView.js`) — list/load/
  delete, per-deck legality badge, sleeve picker.
- **Deck analysieren**: local/static deck analysis (`analyzeView.js` +
  `deckAnalysis.js`) — mana curve, type distribution, land archetypes,
  Command Zone categories, and a Commander-Brackets-style heuristic. Pure
  client-side, no backend call — see `Done_Frontend.md` "Deck analysis".
- **Goldfisch**: solo play against the real backend rules engine
  (`goldfishView.js`/`gameBoardView.js` → `POST /api/game/*`). Pick a
  saved (legal) deck, mulligan, then step through the turn — play lands,
  tap mana, cast (incl. targets/{X}), attack — from the server's
  `legal_actions`, with rewind/restart.
- **Replay** (Puzzle mode): build an arbitrary board state and play from
  it (`replayView.js`, shares `gameBoardView.js` with Goldfisch) — see
  `backend/mtg_analyzer/services/replay.py`.
- **Multiplayer**: a stub tab (`multiplayerView.js`) — the backend route
  returns 501 until the interactive priority loop is wired into a session.
- **Einstellungen**: player name / server address (`connectionSettingsView.js`),
  connection status, uploaded token art + card-back sleeves.
- **Karten-Cache**: browse every card currently cached server-side
  (`cachedCardsView.js`).
- **Engine-Status**: a static, hand-maintained page (`implementationStatusView.js`)
  documenting what the rules engine actually supports — see CLAUDE.md
  "Implementation state".

## Structure

```text
index.html
src/
  styles/main.css
  js/
    app.js                      sidebar wiring, entry point
    state.js                    tiny pub/sub store (parsed deck + image cache)
    cookies.js / settings.js    device-local prefs (player name, server URL)
    connectionStatus.js         header connection indicator (polls /api/health)
    parser.js                   per-section decklist parsing (local pre-check)
    cardImages.js               card artwork lookup via the backend (batched, cached)
    cardTile.js                 shared card-tile rendering (mana cost, badges)
    cardHoverDetail.js          floating card-detail-on-hover panel
    deckImportView.js           "Deck editieren" tab
    savedDecksView.js           "Decks verwalten" tab (list/load/delete, legality)
    analyzeView.js / deckAnalysis.js   "Deck analysieren" tab (static analysis, no backend call)
    goldfishView.js             "Goldfisch" tab, server-driven solo play
    replayView.js                "Replay" (Puzzle mode) tab
    gameBoardView.js             shared board rendering (Goldfisch + Replay)
    multiplayerView.js          "Multiplayer" tab (stub)
    connectionSettingsView.js   "Einstellungen" tab (player/server, token art, sleeves)
    cachedCardsView.js          "Karten-Cache" tab
    implementationStatusView.js "Engine-Status" tab
    api.js                      backend HTTP client (/api/decks, /api/cards, /api/game, …)
    gameSocket.js                WebSocket client (kept for future multiplayer)
```

See `ToDo_Frontend.md` / `Done_Frontend.md` for feature status, and
[`../user-docs/`](../user-docs/) for how to actually use each tab.
