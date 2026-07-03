# Frontend TODO

Status: Step 1 done — decklist import via three sections
(Commander/Mainboard/Sideboard, client-side parsing), a mock play area
with card artwork pulled from Scryfall (see [README.md](README.md)).
Confirmed working in-browser (images load on the play area). Everything
below is not yet implemented.

## Import — follow-ups

- [ ] Direct import from external deck builders (Moxfield, Archidekt,
      …) was tried and reverted: fetching `api.moxfield.com` directly
      from the browser hit Cloudflare bot protection (HTTP 403 on the
      deck page, `/download`, and both v2/v3 API endpoints when tested
      by hand). Revisit once the backend has an HTTP server that can
      proxy the request server-side (`GET /api/import/moxfield/{id}`)
      — still no guarantee it gets past bot protection, but removes
      the browser-CORS obstacle at least.

## Backend integration (blocks most of the rest)

- [ ] Replace `parser.js`'s client-side parsing with a call to a real
      `POST /api/decks` endpoint once the backend has a
      `DecklisteParser` + card database (docs/02, UC1). Keep the
      client-side parser as an optimistic local pre-check.
- [ ] Resolve parsed card names against the card database → get mana
      cost, type_line, oracle_text, power/toughness, image URIs. Right
      now the frontend only knows a card's name and quantity.
- [ ] Real Commander legality: color identity, ban list, partner
      rules. Currently only structural checks (100 cards, singleton,
      exactly one commander) run locally.
- [ ] Deck persistence: save/load decks via API instead of re-pasting
      the decklist every time.
- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Card display

- [x] Card artwork on the board (`src/js/cardImages.js`): resolved from
      Scryfall's `/cards/collection` batch endpoint (CORS-enabled,
      unlike Moxfield — verified by hand), cached per session, falls
      back to the plain name box while loading / if not found. Uses
      `<img loading="lazy">` for viewport-based deferred loading
      (docs/06_CARD_GRAPHICS_AND_LAZY_LOADING.md) rather than a custom
      IntersectionObserver — revisit if that's not enough once card
      counts grow (opponent boards, graveyard piles, etc.). Confirmed
      working in-browser.
- [ ] Same artwork lookup for the deck-import card lists (Commander/
      Mainboard/Sideboard results), not just the play area.
- [ ] Mana cost, type, oracle text on cards — not just name + image
      (docs/06, docs/05 PART 1). Needs the backend card database;
      Scryfall's collection response already carries this data, so
      `cardImages.js` could return more than just image URIs if this
      becomes valuable, but that's mixing "backend integration" and
      "meanwhile client-side" concerns — resolve backend-side first.
- [ ] Card detail/expanded view on click/hover (docs/05 "Hybrid" hand
      layout).

## Game engine hookup (replaces `boardEngine.js`)

- [ ] Swap the local mock (`boardEngine.js`) for real server game
      state once the backend's game engine exists (docs/07,
      docs/02 UC3). `boardView.js` already only reads from `state.js`,
      so this should be a state-source swap, not a UI rewrite.
- [ ] WebSocket client: connect to `/ws/game/{game_id}`, receive
      `game_state_update`, send `player_action` (docs/04 PART 4).
- [ ] Legal-actions-driven UI: only show actions the server says are
      legal, instead of letting any hand card be clicked
      (`moveToBattlefield` today has no rule checks at all — see
      docs/05 PART 3).
- [ ] Targeting UI: select target(s) when a spell/ability requires it
      (docs/05 PART 5).
- [ ] Activated abilities on permanents (tap for mana, etc.) (docs/05
      PART 6).
- [ ] Stack display: show pending spells/abilities in LIFO order
      (currently a static "leer" placeholder).
- [ ] Phase/step/turn indicator + "pass priority" control (docs/03
      R2.1, R2.4).
- [ ] Mulligan per real rules (London mulligan: draw 7, put N back) —
      current mulligan is a full reshuffle+redraw, not accurate.

## Multiplayer

- [ ] Second player / opponent zones are currently permanent
      placeholders ("kein Gegner-Deck geladen"). Needs matchmaking or
      a local "load second deck" flow before this can show anything
      real (docs/02 UC4, docs/04 S5).
- [ ] Hide opponent's hand contents (only show count) once there's a
      real opponent.
- [ ] Turn/priority indicator for whose turn/priority it is.
- [ ] Timeout handling for a slow opponent (docs/04 S2).

## Auth & sessions

- [ ] Login/signup pages (docs/04 PART 4 REST endpoints).
- [ ] Auth token storage + attach to API/WebSocket calls.
- [ ] Reconnect flow if the browser refreshes mid-game (docs/04 S1).

## Deck analysis (UC2)

- [ ] "Analyze deck" button + results view (win conditions, archetype,
      synergies, cohesion score, issues) once
      `POST /api/decks/{id}/analyze` exists (docs/02 UC2, docs/04
      Phase 6).
- [ ] Cache indicator ("Analysis from X ago").

## Bot mode (UC5)

- [ ] "Bot Play" vs "Manual Play" selector before a game starts.
- [ ] Visualize bot actions in real time, with a speed control.

## Cleanup / polish

- [ ] Tooling: no Node/npm is installed on this machine, so there's no
      linter, formatter, or automated JS test runner for this code
      yet. Logic was verified ad hoc via `osascript -l JavaScript`
      (JavaScriptCore) — worth replacing with a real test setup once
      Node is available.
- [ ] Keyboard shortcuts (docs/05 PART 9).
- [ ] Accessibility: alt-text on cards, tab navigation, high-contrast
      mode (docs/05 PART 10).
- [ ] Responsive/mobile layout — only checked at desktop width so far.
