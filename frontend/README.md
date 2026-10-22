# Frontend (Browser Client)

Plain HTML/CSS/JS (ES modules), no build step and no runtime dependencies.
Development-only linting is installed separately by `../setup_dev.sh` into a
project-local `frontend/.nodeenv` and `frontend/node_modules`; it is not needed
to run the client. The browser client deliberately avoids a bundler — it can
be extended to React/Vite later (see
[docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md](../docs/concepts/04_SERVER_CLIENT_ARCHITECTURE.md))
without changing how it's served in the meantime.

After the development setup, run:

```bash
PATH="$PWD/.nodeenv/bin:$PATH" .nodeenv/bin/npm run lint
```

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
  database — see `Done_Frontend.md` "Deck Import & Backend Integration".
- **Decks verwalten**: saved decks (`savedDecksView.js`) — list/load/
  delete, per-deck legality badge, sleeve picker.
- **Deck analysieren**: local/static deck analysis and advice
  (`analyzeView.js` + `deckAnalysis.js`) — mana curve, type distribution,
  land archetypes, Command Zone categories, a Commander-Brackets-style
  heuristic, and mana-curve / Commander Spellbook combo recommendations.
  Combo matching uses the local backend snapshot; see
  `Done_Frontend.md` "Deck Analysis (frontend)".
- **Goldfisch**: solo play against the real backend rules engine
  (`goldfishView.js`/`gameBoardView.js` → `POST /api/game/*`). Pick a
  saved (legal) deck, mulligan, then step through the turn — play lands,
  tap mana, cast (incl. targets/{X}), attack — from the server's
  `legal_actions`, with rewind/restart.
- **Replay** (Puzzle mode): build an arbitrary board state and play from
  it (`replayView.js`, shares `gameBoardView.js` with Goldfisch) — see
  `backend/mtg_analyzer/services/replay.py`.
- **Multiplayer**: a real two-player game against the same engine
  (`multiplayerView.js` + `lobbySocket.js` → `/api/multiplayer/*`,
  `/ws/lobby`). **Setup** is the lobby (tables, seats, deck picks, bots,
  take-back and mulligan options); **Board** is the shared game, driving
  `gameBoardView.js` through an injected transport, with RULE 117 priority
  played out for real and hidden zones redacted server-side.
- **Profil**: the player name (`profileView.js`) — who you are, split out of
  Einstellungen so it doesn't read as a connection setting.
- **Einstellungen**: server address (`connectionSettingsView.js`), connection
  status, uploaded token art + card-back sleeves, auto-pass preferences.
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
    multiplayerView.js          "Multiplayer" tabs (Setup lobby + shared Board)
    lobbySocket.js               /ws/lobby client — presence + per-player view push
    profileView.js              "Profil" tab (player name)
    connectionSettingsView.js   "Einstellungen" tab (server, token art, sleeves)
    cachedCardsView.js          "Karten-Cache" tab
    implementationStatusView.js "Engine-Status" tab
    api.js                      backend HTTP client (/api/decks, /api/cards, /api/game, …)
    gameSocket.js                WebSocket client (kept for future multiplayer)
```

See [`../docs/implementation-state/BACKLOG.md`](../docs/implementation-state/BACKLOG.md)
(open work — the `VIS` tickets are the frontend ones) and
[`../docs/implementation-state/Done_Frontend.md`](../docs/implementation-state/Done_Frontend.md)
(what shipped, and why) for feature status, and
[`../user-docs/`](../user-docs/) for how to actually use each tab.

## Synthesized game audio

Enable **Spiel-Sounds / Game sounds** under **Einstellungen / Settings → Sound**;
volume and mute are saved in cookies and apply to all game modes. The board
has no audio controls or preview links. Audio starts on a user gesture and stays silent
in hidden tabs. `sound-lab.html` offers individual tap/untap/damage samples,
eight spell types and all 32 WUBRG colour subsets (including colourless).
This standalone development tool can be opened directly on the frontend
server; it is not linked from the application.

`src/js/gameAudio.js` exports `createGameAudio()` and the pure
`gameAudioEvents(previousView, nextView)` adapter. `play({kind, card, amount})`
accepts `tap`, `untap`, `draw`, `turn_end`, `damage`, `land`, `activate` and `cast`; cards can supply
`type_line` and an explicit `colors` array. Cast gestures have distinct rhythms and registers: creature impact, instant
air flick, sorcery swell, enchantment chimes, inharmonic artifact strike,
planeswalker fanfare and battle double hit. Cast colour layers are quieter
and delayed so the type stays prominent. Each multicolour motif uses
normalized layers rather than a separate preset for each combination.

The synthesis layers softly filtered, correlated noise with damped resonances,
subtle pitch/timing variations and a short stereo room response. Tap/untap
are dry clicks under 30 ms with no room send. Land plays use a soft card
contact and low settling body; impacts use a low body and textured attack. Muting/stopping also clears the room tail.

The board consumes confirmed, growing move logs and public table announcements.
Initial loads, duplicate views and undo produce no sounds. Tap changes and
damage are grouped per update, with bounded voices and events for bot bursts.
Land sounds follow confirmed `play_land` announcements, including lands
played tapped; a land entering through an effect alone does not trigger them.
Draws use confirmed draw statistics (including effect draws, independent of
net hand size); multiple draws form one short paper shuffle. The turn handoff
tone follows an increased internal turn number, including extra turns.
Passing priority or setting a yield alone stays silent.
Damage uses actual damage statistics (combat and noncombat share an impact),
not life loss or a mere transition into the combat damage step. Changes that
happen and are reversed entirely within one server update cannot be heard as
individual taps. The current board payload lacks actual colours, so its
adapter falls back to mana cost: colour indicators and Devoid need explicit
`colors` to sound accurate. Unknown or unnamed sources use a neutral motif.

Verification: `backend/venv/bin/python frontend/tests/test_game_audio.py`
(from repository root) checks real Chromium controls, preference persistence,
settings/board integration, event deduplication and offline rendered audio for all
8 × 32 spell/type-colour combinations plus action sounds.
