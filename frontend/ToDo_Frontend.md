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
- [x] Real Commander legality: color identity, ban list, partner
      rules — done server-side
      (`backend/mtg_analyzer/services/commander_legality.py`), returned
      as extra `validation.errors`/`.warnings` from `POST /api/decks`.
      Still only structural checks (100 cards, singleton, exactly one
      commander) run locally/client-side; the frontend doesn't call
      `POST /api/decks` yet at all (see "Backend integration" above),
      so the real checks aren't reachable from the UI until that's
      wired up.
- [x] Deck persistence: save/load decks via API instead of re-pasting
      the decklist every time — see "Saved decks" below.
- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Connection settings

- [x] Layout: a collapsible left sidebar (`#sidebar`/`.sidebar-nav` in
      `index.html`, toggled by a burger button — `app.js` toggles the
      `.collapsed` class) replaced the old top-bar row of tab buttons.
      The header now holds only the title and the connection badge
      (`justify-content: space-between`). Nav entries: "Deck erstellen"
      (import), "Decks verwalten" (saved decks), "Deck analysieren"
      (new placeholder, see "Deck analysis (UC2)" below — no backend
      endpoint to call yet), "Spielfläche", "Einstellungen" (connection
      config), "Karten-Cache". Same `.tab-button`/`data-tab` + `showTab()`
      wiring as before (`app.js`), just relocated — collapsing the
      sidebar only hides the nav, it doesn't change which tab is active.
- [x] Header connection indicator (`src/js/connectionStatus.js`'s
      `renderConnectionIndicator`, mounted in `app.js` into
      `#header-connection-status`): a dot + label ("Verbunden"/"Nicht
      erreichbar"/"Prüfe …"), visible on every tab, polling
      `GET /api/health` every 5s (`api.js`'s `checkHealth`). Status is
      a small shared pub/sub store (`getConnectionStatus`/
      `subscribeConnectionStatus`/`refreshConnectionStatus`) so the
      header indicator and the "Verbindung" tab's own status line stay
      in sync off one poll instead of each polling separately.
- [x] "Einstellungen" tab (`connectionSettingsView.js`): a player-name
      field and a server-address field (defaults to
      `http://localhost:8000`, same default as `api.js` always used),
      "Speichern" and "Verbindung testen" buttons, plus the live status
      line. Saving normalizes the URL (trims whitespace/trailing
      slash) and re-checks immediately — no page reload needed, since
      `api.js`/`gameSocket.js` resolve the server address fresh on
      every call via `settings.js`'s `getServerUrl()` rather than
      reading a fixed constant once at module load.
- [x] Settings persisted client-side in a cookie
      (`src/js/cookies.js`, `settings.js`; `mtg_server_url`,
      `mtg_player_name`, 1-year expiry) — browser/device-local only, not
      synced to the backend (there's no user-account concept yet, see
      backend/ToDo_Backend.md "Auth & persistence"). The player name
      isn't used anywhere in the UI yet; today it only supplies the
      default `player_id` for `gameSocket.js`'s `sendPlayerAction`,
      which nothing calls yet either (see "Game engine hookup" below).

## Saved decks

- [x] "Deck importieren" tab: a name field + "Speichern" button
      (`deckImportView.js`) calls `POST /api/decks/save`. Saves the raw
      textarea contents regardless of parse/validation status (matches
      the backend, which doesn't require either). Re-clicking
      "Speichern" after the first save updates that same record instead
      of creating a duplicate (tracked via the returned `id`, reset only
      by loading the sample deck or a different saved deck — typing in
      the textareas doesn't reset it).
- [x] "Gespeicherte Decks" tab (`savedDecksView.js`): lists every saved
      deck (name, save timestamp) via `GET /api/decks`, lazily on first
      open like the other lazy tabs. "Laden" fetches the full deck
      (`GET /api/decks/{id}`) and feeds it into the import view's
      textareas via `deckImportView.js`'s exported `loadDeck()`, which
      then runs the normal parse+resolve+submit flow — same as pasting
      the text by hand. "Löschen" calls `DELETE /api/decks/{id}` after
      a `confirm()` prompt.
- [ ] No rename/duplicate-as-new actions yet — only save (create/update
      via the tracked id) and delete.
- [ ] Same browser-verification caveat as "Card display" below: checked
      via API replay against a running backend (parse → save → list →
      get → update → resolve → delete), not an actual rendered page.

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
      card currently in the backend's cache — image (shown in full,
      no crop, via `object-fit`-free `<img>` sizing), name, type, mana
      cost as colored/number emoji, oracle text, keywords, set/rarity.
      Fetches `GET /api/cards` lazily (only once the tab is first
      opened, via a `view-shown` event dispatched by `app.js`'s
      `showTab`), with a manual refresh button since the cache grows as
      decks get imported elsewhere in the app. Same browser-verification
      caveat as above.
- [ ] Mana cost emoji don't distinguish hybrid/Phyrexian symbols from
      plain ones (e.g. `{W/U}` renders as a plain ⚪, not "W or U") —
      inherited from the backend's flattened `Card.mana_cost`, see
      backend/ToDo_Backend.md "Mana cost model (Backlog)". Generic mana amount
      is derived client-side (`converted_mana_cost` minus pip total)
      rather than stored, for the same reason.
- [x] Artwork + full card details for the deck-import card lists
      (Commander/Mainboard/Sideboard): a "Detailansicht" checkbox in the
      result panel (`deckImportView.js`) switches all three lists from
      the plain name+qty `<ul>` to the same image/mana-cost/oracle-text
      tile grid as the Karten-Cache tab, with a quantity badge added.
      Shared rendering logic lives in `cardTile.js` now (`renderCardTile`,
      `renderManaCost`, ...) so the two views don't duplicate it.
      Off by default (the plain list stays the fast/quiet default); a
      card not yet resolved (data still in flight) shows a "Lädt …"
      placeholder tile rather than blocking the toggle. Mainboard and
      Sideboard scroll internally in a `.scrollable` box sized in `vh`
      (adapts to the window, and gets a taller cap in detail mode since
      a tile row is much taller than a text row — see `.scrollable` /
      `.scrollable.detail-mode` in main.css) instead of a fixed pixel
      height. Toggling the checkbox scrolls the result panel back into
      view at the top — without it, switching modes changes the panel's
      height enough that the page could be left scrolled past the new
      (shorter or taller) content, looking like the toggle silently did
      nothing.
- [x] Mana cost, type, oracle text on cards in the play area — not just
      name + image (docs/06, docs/05 PART 1) — done via "Card detail on
      hover" below rather than always-on inline text (the board's `.card`
      tiles are too small to fit it inline without redesigning the grid).
- [x] Card detail/expanded view on click/hover (docs/05 "Hybrid" hand
      layout): `src/js/cardHoverDetail.js` — one floating panel, shown via
      a single delegated `mouseover`/`mousemove`/`mouseout` listener on
      `document` (set up once in `app.js`'s `initCardHoverDetail()`)
      rather than per-element listeners, so it survives re-renders and
      any view opts in just by adding `data-hover-card="<name>"` to an
      element — no per-view wiring needed. Reads card data from
      `cardImages.js`'s existing resolve cache (`getResolvedCard`), so it
      shows "Lädt …" and then upgrades to full details (image, mana cost,
      type, oracle text, power/toughness, keywords) once resolution lands,
      without needing a fresh mouseover. Wired into the board's `.card`
      tiles (`boardView.js`, replacing the old plain-name `title` tooltip)
      and the deck-import plain card list (`deckImportView.js`'s
      non-detail-mode `<li>` rows) — not needed in detail-mode tiles or
      the Karten-Cache tab since those already show full details inline.
      On the board specifically, a "Kartendetails bei Hover" checkbox
      (next to the draw/mulligan buttons) makes it on/off-able — added
      after a report that hover wasn't visibly doing anything on the
      board and the root cause couldn't be confirmed in this no-real-browser
      environment (see below). Unchecking it omits the
      `data-hover-card` attribute on re-render (falls back to a plain-name
      `title` tooltip) rather than disabling the global listener, so other
      views keep working regardless of this view-local toggle. Defaults
      to on. Verified: real backend/frontend dev servers replaying
      import → resolve → cache flow confirm the resolved card fields the
      tooltip needs (`type_line`, `mana_cost`, `oracle_text`, ...) are all
      present, and that the running dev server actually serves the
      checkbox markup; the delegated-listener and toggle logic themselves
      (content refresh mid-hover, descendant mouseout, scroll-hide,
      attribute presence flipping with the checkbox) were verified via
      mock-DOM `osascript -l JavaScript` harnesses (same approach as the
      earlier detail-mode-toggle bugfix) since no real browser automation
      is available here (`safaridriver` starts but can't launch/attach to
      a Safari instance in this sandbox — no display session) — **still
      not confirmed by an actual rendered, moused-over page**; if the
      checkbox is checked and hovering still shows nothing, that points
      at a real bug this environment couldn't catch (get exact browser +
      console errors, and whether a hard refresh was tried, before
      digging further).

## Game engine hookup (replaces `boardEngine.js`)

- [ ] Swap the local mock (`boardEngine.js`) for real server game
      state once the backend's game engine exists (docs/07,
      docs/02 UC3). `boardView.js` already only reads from `state.js`,
      so this should be a state-source swap, not a UI rewrite.
- [x] WebSocket client connection plumbing (`src/js/gameSocket.js`):
      `connectGameSocket(gameId, handlers)` opens a `ws(s)://.../ws/game/{game_id}`
      connection (same origin-config convention as `api.js`), sends
      `player_action` via `sendPlayerAction(action, playerId)`, and
      dispatches incoming `game_state_update`/`error` messages to
      caller-supplied handlers (docs/04 PART 4). Verified against a
      real running backend with a scripted two-client round trip
      (no browser/Node available to test from an actual page, see
      "Cleanup / polish" below). Deliberately not wired into
      `boardEngine.js`/`boardView.js` yet — the backend has no game
      engine behind it either (it just relays the action back out, see
      `../backend/ToDo_Backend.md` "HTTP API foundation"), so there's
      no real state to switch to; that swap is its own step below.
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

- [x] Nav entry exists ("Deck analysieren" in the sidebar,
      `analyzeView.js`) but only renders a static "not implemented yet"
      placeholder — added so the menu structure matches the intended
      feature set ahead of the backend actually having anything to call.
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
