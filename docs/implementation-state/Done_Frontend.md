# Frontend — Done

Completed frontend work, split out of `ToDo_Frontend.md` (which now holds
only open items). Section headers mirror that file.

## Backend integration

- [x] `parser.js`'s client-side parsing is now the *optimistic local
      pre-check*, with `POST /api/decks` as the authoritative follow-up:
      `deckImportView.js`'s `parseCurrentSections` parses locally for
      instant feedback (a "Wird serverseitig geprüft …" pending badge),
      then calls `submitDeck` (`api.js`) and **replaces** `state.deck`
      with the server's response, which becomes what's rendered.
- [x] Resolve parsed card names against the card database → mana cost,
      type_line, oracle_text, power/toughness, image URIs (`api.js`'s
      `resolveCards`/`cardImageUrl`, used by `cardImages.js`).
- [x] Real Commander legality surfaced from `POST /api/decks`
      (`validation.errors`/`.warnings`), with the specific offending
      cards marked individually (❗) via `validation.bannedCardNames`/
      `.colorIdentityViolationNames` (`cardTile.js`'s `illegalReason`) —
      distinct from the 🛑 "not found" marker.
- [x] Deck persistence: save/load decks via API — see "Saved decks".

## Connection settings

- [x] Collapsible left sidebar (`#sidebar`/`.sidebar-nav` in
      `index.html`, burger toggle in `app.js`) replaced the old top-bar
      tabs. Nav entries: "Deck editieren" (import), "Decks verwalten",
      "Deck analysieren" (placeholder), "Goldfisch", "Multiplayer",
      "Einstellungen", "Karten-Cache". `.tab-button`/`data-tab` +
      `showTab()` wiring in `app.js`.
- [x] Header connection indicator (`connectionStatus.js`): dot + label,
      visible on every tab, polling `GET /api/health` every 5s. Shared
      pub/sub store keeps the header and the "Einstellungen" status line
      in sync off one poll.
- [x] "Einstellungen" tab (`connectionSettingsView.js`): player-name +
      server-address fields (default `http://localhost:8000`), "Speichern"
      / "Verbindung testen", live status. Saving normalizes the URL and
      re-checks immediately (no reload — `getServerUrl()` is read fresh
      per call).
- [x] Settings persisted in a cookie (`cookies.js`, `settings.js`;
      `mtg_server_url`, `mtg_player_name`, 1-year expiry) — device-local.

## Saved decks

- [x] "Deck editieren" save: name field + two buttons (`deckImportView.js`)
      → `POST /api/decks/save`. **"Aktualisieren"** overwrites the
      loaded/last-saved deck (sends its `id`); **"Als neues speichern"**
      always creates a fresh deck. Split from a single "Speichern" that
      silently overwrote the loaded deck (surprising/destructive).
      "Aktualisieren" is disabled until a deck is loaded/saved.
- [x] "Decks verwalten" tab (`savedDecksView.js`): lists saved decks via
      `GET /api/decks` (lazy). "Laden" fetches the full deck and feeds it
      into the editor's textareas (`loadDeck()`); "Löschen" →
      `DELETE /api/decks/{id}` after a confirm. Each row shows a
      **legality badge** from `GET /api/decks/{id}/validation` (per deck,
      lazily, in parallel): 🛑 + reasons (tooltip) for illegal, ✅ for
      legal.

## Card display

- [x] Card artwork (`cardImages.js`) via `POST /api/cards/resolve` +
      `GET /api/cards/{id}/image` (backend cache) rather than the browser
      calling Scryfall; cached per session client-side, `<img
      loading="lazy">`.
- [x] "Karten-Cache" tab (`cachedCardsView.js`): browse every cached card
      (image, name, type, mana cost emoji, oracle text, keywords,
      set/rarity), `GET /api/cards` lazily with a manual refresh.
- [x] Detail-view tiles for the deck-import lists: a "Detailansicht"
      checkbox switches all three lists to an image/mana-cost/oracle-text
      tile grid (`cardTile.js`, shared with Karten-Cache), with 🛑
      "not found" tiles (`renderCardTileNotFound`) and internal scrolling
      (`.scrollable`).
- [x] Card detail on hover (`cardHoverDetail.js`): one floating panel via
      a single delegated listener on `document` (set up in
      `initCardHoverDetail()`), so any view opts in with
      `data-hover-card="<name>"`. Reads `cardImages.js`'s resolve cache;
      shows "Lädt …" then upgrades. Wired into the goldfish board's
      `.card` tiles (`goldfishView.js`'s `objCard`) and the deck-import
      plain list.
- [x] Mana cost emoji now render hybrid/Phyrexian symbols faithfully
      instead of collapsing them to a plain pip: `cardTile.js`'s
      `renderManaCost` parses the raw `mana_cost_string` token-by-token
      (`{W/U}` → "(⚪/🔵)", `{2/W}` → "(2️⃣/⚪)", `{W/P}` → "(⚪/🩸)",
      `{X}`/`{Y}`/`{Z}` → the letter itself), mirroring the backend's
      `ManaSymbol` kinds (`models/mana_cost.py`). Falls back to the old
      flattened-pip approximation only when `mana_cost_string` is empty
      (cards cached before that field existed — same fallback the
      backend's `ManaCost.from_card` uses, see backend Done "Mana cost
      model"), so a genuinely free card (a land) still renders as
      nothing.

## Game engine hookup

- [x] Goldfisch-Modus wired to the real backend engine
      (`goldfishView.js`), its own top-level **"Goldfisch"** sidebar tab
      (`#view-goldfish`). Deck chosen from a **dropdown of saved decks**
      (`GET /api/decks`); selecting fetches legality
      (`GET /api/decks/{id}/validation`) and **only a legal deck enables
      "Start"** (illegal → 🛑 + reasons). Start posts `deckId` to
      `POST /api/game/goldfish`, then renders the server's authoritative
      `GameState` and drives it with validated actions (advance step,
      auto-turn, play land, tap mana, cast, attack — from `legal_actions`),
      plus **Zurücknehmen** (rewind) and **Neu starten** (restart).
      `app.js` creates one persistent `createGoldfishView()` so a running
      session survives tab switches.
- [x] The old local, rule-less "preview" board and its `boardEngine.js`
      were removed (the `board` field dropped from `state.js`), and the
      combined "Spielfläche" tab (`boardView.js`, a Goldfisch/Multiplayer
      mode switcher) was split into **two separate sidebar tabs**,
      "Goldfisch" and "Multiplayer" — the multiplayer stub moved into its
      own `multiplayerView.js`. `boardView.js`/`boardEngine.js` are gone.
- [x] WebSocket client plumbing (`gameSocket.js`):
      `connectGameSocket(gameId, handlers)` opens `ws(s)://.../ws/game/{id}`,
      sends `player_action`, dispatches `game_state_update`/`error`.
      Solo play goes through the REST session API instead; this is kept
      for the eventual multiplayer push channel, not yet wired in.
- [x] Stack display: goldfish shows the stack in LIFO order
      (`.gf-stack` from `state.stack`), with a "Priorität abgeben (Stack
      auflösen)" control (pass_priority) that resolves it one object at a
      time so you can respond.
- [x] Phase/step/turn indicator: goldfish's `.gf-topbar` shows the turn
      number and current phase/step (German labels).
- [x] Actions shown **directly under the affected cards**
      (`goldfishView.js`, `.gf-card-slot`/`.gf-card-actions`): a hand card
      shows "🌳 Land spielen" / "✨ Zaubern"; a land shows a **tap button
      per mana option** (dual lands get one per colour — the "🟢/🔵" choice
      matching the backend `tap_for_mana` `option_index`). Attacking stays
      an aggregate "⚔️ Angreifen (N)" control (swings with every able
      creature). Built from the session's per-object `legal_actions`.
- [x] Graveyard **and Exile** zones render their cards (`.gf-graveyard`/
      `.gf-exile`, from `state.players[0].graveyard`/`exile`).
- [x] Pending-choice UI: a library search surfaces a "🔎 Suche …" panel
      (`.gf-choice`) listing eligible cards as pick buttons (+ "Nichts
      wählen" when optional); the board dims (`.goldfish.choosing`) and
      other actions are gated until the choice is answered (`choose`/
      `decline`), matching the backend `state.pending_choice`.
- [x] Loading screen before a goldfish game renders: `start()` preloads
      every deck card's artwork (`cardImages.js`'s `preloadCardImages`,
      real `Image()` fetches, not just resolving the URL) with a progress
      bar (`goldfish-loading` phase) before calling `POST
      /api/game/goldfish`, so the board never pops in card art turn by
      turn. Fixes the "images not always loaded" bug — the goldfish board
      previously never triggered `resolveCardImages` for a deck unless it
      had separately been opened in "Deck editieren".
- [x] Mulligan/setup phase (London mulligan) before the board is
      playable: a new `goldfish-mulligan` screen shows the opening hand
      with "Mulligan" (draw a fresh 7) / "Hand behalten" controls, driven
      by the session's `setup: {complete, mulligan_count}` + `mulligan`/
      `keep_hand` actions (`game_session.py`). Keeping after N mulligans
      requires selecting N cards from hand to put on the bottom first
      (click-to-toggle, `card.selected-bottom`). All other actions are
      rejected server-side until the hand is kept.
- [x] X-spell casting (RULE 601.2b): a hand/command-zone card whose cost
      has `{X}` gets a number input next to its cast button instead of a
      plain "✨ Zaubern" (`goldfishView.js`'s `cardActionButtons`, keyed
      off `legal_actions`' new `has_x`/`max_x`, capped at `max_x` by
      default) — clicking reads the input's current value at click time
      (`data-cast-x`/`data-x-input`, wired in `wire()`) and sends it as
      `x` on the `cast_spell` action. `.gf-cast-x` in `main.css`.

## Multiplayer

- [~] A dedicated **"Multiplayer"** sidebar tab (`multiplayerView.js`):
      calls `POST /api/game/multiplayer` and shows the backend's 501
      "not yet" message. Stubbed on purpose — the interactive priority
      loop isn't built server-side yet.

## Deck analysis (UC2)

- [x] Nav entry ("Deck analysieren", `analyzeView.js`) rendering a static
      "not implemented yet" placeholder — the menu structure matches the
      intended feature set ahead of the backend endpoint existing.
