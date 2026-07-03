# Frontend TODO

Status: Step 1 done — decklist import via three sections
(Commander/Mainboard/Sideboard, client-side parsing), a mock play area
with card artwork (see [README.md](README.md)). Card data/images now
come from the backend's cache (`POST /api/cards/resolve`,
`GET /api/cards/{id}/image`) instead of the browser calling Scryfall
directly — see "Card display" below. Everything else below is not yet
implemented.

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
- [x] Resolve parsed card names against the card database → get mana
      cost, type_line, oracle_text, power/toughness, image URIs
      (`api.js`'s `resolveCards`/`cardImageUrl`, used by
      `cardImages.js`). The deck-import result list itself still only
      renders name + qty though — see "Card display" below.
- [ ] Real Commander legality: color identity, ban list, partner
      rules. Currently only structural checks (100 cards, singleton,
      exactly one commander) run locally.
- [ ] Deck persistence: save/load decks via API instead of re-pasting
      the decklist every time.
- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Card display

- [x] Card artwork on the board (`src/js/cardImages.js`): resolved via
      the backend's `POST /api/cards/resolve` (batch name lookup) and
      `GET /api/cards/{id}/image` (cached image bytes) instead of
      calling Scryfall directly from the browser — the backend
      downloads/caches on first use, so repeat lookups by anyone are
      served locally (docs/06, docs/08_CARD_CACHE_EXPORT_IMPORT.md).
      Cached per session client-side too, falls back to the plain name
      box while loading / if not found. Uses `<img loading="lazy">` for
      viewport-based deferred loading rather than a custom
      IntersectionObserver — revisit if that's not enough once card
      counts grow (opponent boards, graveyard piles, etc.). Verified by
      replaying the exact request sequence (`POST /api/decks` →
      `POST /api/cards/resolve` → `GET /api/cards/{id}/image`) against
      a running backend; **not yet confirmed by an actual browser
      render** — no Node/npm/Playwright/chromium-cli available in this
      environment to drive one (see "Cleanup / polish" below).
- [x] "Karten-Cache" tab (`src/js/cachedCardsView.js`): browse every
      card currently in the backend's cache — image, name, type,
      mana cost, oracle text, keywords, set/rarity. Fetches
      `GET /api/cards` lazily (only once the tab is first opened, via a
      `view-shown` event dispatched by `app.js`'s `showTab`), with a
      manual refresh button since the cache grows as decks get
      imported elsewhere in the app. Same browser-verification caveat
      as above.
- [ ] Same artwork lookup for the deck-import card lists (Commander/
      Mainboard/Sideboard results), not just the play area.
- [ ] Mana cost, type, oracle text on cards in the play area — not just
      name + image (docs/06, docs/05 PART 1). The data is available
      now (see above); this is purely a `boardView.js` rendering change.
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
      yet, and no way to drive a real browser for UI verification
      (no Playwright/chromium-cli either) — changes get verified by
      reading the code plus replaying the equivalent API calls against
      a running backend, not by an actual rendered page. Logic was
      verified ad hoc via `osascript -l JavaScript` (JavaScriptCore) in
      the past — worth replacing with a real test + browser-automation
      setup once Node is available.
- [ ] Keyboard shortcuts (docs/05 PART 9).
- [ ] Accessibility: alt-text on cards, tab navigation, high-contrast
      mode (docs/05 PART 10).
- [ ] Responsive/mobile layout — only checked at desktop width so far.
