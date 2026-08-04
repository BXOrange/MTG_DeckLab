# Frontend — Done

**Worklog** (append-only): completed frontend work and *why it was built
that way*. Open work lives in [BACKLOG.md](BACKLOG.md), under `VIS` and the
other categories.

Section headers are stable — a `Done_Frontend.md "<section>"` reference from
the code lands here. Entries written before 2026-07-27 cite a
`ToDo_Frontend.md`/`ToDo_Backend.md` that no longer exists; both were merged
into `BACKLOG.md`, and those mentions have been repointed there.

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

## Import

- [x] "Import Deck" — a sidebar tab of its own (`index.html`'s
      `#view-import-deck`, alongside "Deck editieren" in the
      Deck-Management nav group), separate from `deckImportView.js`
      because a failed import should leave the user on the import
      screen with the error, not dump them into a half-populated editor.
      `importDeckView.js` takes an Archidekt deck link or bare id
      (Moxfield was tried and reverted twice — genuinely
      Cloudflare-blocked, `Done_Backend.md` "Import — follow-up from the
      frontend"), calls `api.js`'s `importArchidektDeck` (`GET
      /api/import/archidekt/{deckId}`), and on success hands the
      `{name, commanderText, mainboardText, sideboardText}` result to an
      `onImported` callback — `app.js` wires that to
      `importView.loadDeck(deck)` (the same method `savedDecksView.js`
      uses to load a saved deck) followed by `showTab('import')`, so a
      successful import behaves exactly like loading a saved deck: the
      textareas fill in and "Deck editieren" opens with "Aktualisieren"
      disabled (no saved-deck id yet, same as loading the sample deck).
      On failure the German error message stays on the Import Deck tab
      instead ("Kein Archidekt-Deck mit ID …", HTTP status, or "Server
      nicht erreichbar").
- [x] Moxfield import, take 3 — not a fetch this time (both earlier
      attempts died to a genuine Cloudflare block, see above), but a
      paste-and-split of Moxfield's own plain-text "Export" output.
      `parser.js`'s `parseMoxfieldExport(rawText)` splits the whole
      exported blob on its "SIDEBOARD:" header into pre-sideboard "body"
      lines + sideboard text; `buildMoxfieldSections(parsed,
      commanderCount)` turns a resolved commander count back into
      `{commanderText, mainboardText, sideboardText}`.
      Commander detection is a **real oracle-text/type-line check**, not
      a text heuristic — Moxfield's export has zero markup for the
      commander at all, so `deckImportView.js`'s `detectMoxfieldCommanderCount`
      resolves the first (and, if eligible, second) body line's actual
      card data via the existing `resolveCardImages` (same lazy card
      cache every other view uses) and asks `parser.js`'s
      `isCommanderCandidate(card)` — legendary creature, or oracle text
      containing "can be your commander" (RULE 903.3's exception
      wording, e.g. Comet, Stellar Pup) — then, for a second line,
      `canPairAsCommanders(cardA, cardB)` (mirrors the backend's
      `commander_legality._can_pair`: Partner / "Partner with X").
      Renders the sideboard-only split immediately, then refines the
      commander/mainboard boundary once the lookup resolves. An earlier
      version used a purely textual heuristic (longest alphabetically-
      sorted suffix of the pre-sideboard lines) before this real check
      replaced it same-session; both were verified against two real
      exports (2026-07-21, one 2-commander/Partner deck, one
      1-commander deck) via a live Playwright run against the running
      app — including the case that actually distinguishes the two
      approaches: example 2's mainboard opens with a *second* legendary
      creature (Abaddon the Despoiler) right after the real commander,
      which has no Partner and correctly stays out of the Commander
      section since it can't pair, not merely because it "sorted into
      place". Wired into `deckImportView.js` as a `paste` handler on the
      Mainboard textarea, gated on the pasted text containing a
      `SIDEBOARD:` line (the one unambiguous "this is a whole export"
      signal) so an ordinary multi-line paste isn't mis-split.

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
- [x] "Als Cube behandeln" checkbox (2026-07-17, `deckImportView.js`, next
      to the author field) flags a saved deck as a card pool (`isCube` —
      `backend/mtg_analyzer/models/deck.py`'s `is_cube`) rather than a
      real Commander deck, so the 100-card/singleton/legality checks don't
      apply — e.g. a curated "cEDH staples" reference list. `savedDecksView.js`
      shows a 🧊 badge and skips the legality-badge fetch for a cube row
      (there's nothing meaningful to check), and gained a matching "Art"
      (Deck/Cube) checkbox-fieldset filter alongside the existing
      color/legality ones.
- [x] **VIS-2 · Rename / duplicate-as-new (2026-08-04).** Two new buttons
      per row in "Decks verwalten" (`savedDecksView.js`), both going
      through the *same* `POST /api/decks/save` the sleeve picker already
      used inline — no new backend route. **"Umbenennen"**: `window.
      prompt` for a new name, then `saveDeck({ ...deck, name })` — same
      `id`, so the server updates in place. **"Duplizieren"**:
      ``saveDeck({ ...deck, id: null, name: `${name} (Kopie)` })`` — an
      absent `id` is exactly "create a new deck" (`SaveDeckRequest`'s own
      doc-comment), and every other field (`sleeveId`/`author`/`isCube`/
      the decklist text) rides along in the spread, so a duplicate is a
      genuine full copy. `createdAt`/`colorIdentity`/`commanders`/
      `analysisId` aren't part of `SaveDeckRequest` at all, so the server
      computes fresh ones for the copy the same way it would for any
      brand-new deck — nothing to reset client-side. Verified live
      (Playwright): save a deck, rename it, refresh → new name shows;
      duplicate it, refresh → a second row with " (Kopie)" appended,
      total count +1, zero console errors.

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
- [x] Double-faced card front/back view on the battlefield board
      (`gameBoardView.js`, shared by Goldfisch/Replay-Spielmodus/
      Multiplayer), 2026-07-27. A real, latent bug first: `resolveImageUrl`
      unconditionally returned the by-name `imageCache` hit's *front* art
      even for an already-`transformed` permanent, since a transformed
      object's `name` (`GameObject.to_dict`) is its *back* face's name and
      the cache was only ever indexed under the deck's front-face name —
      so the miss silently fell through to the (correctly face-aware)
      `card_id`-based fallback, and never actually showed wrong art until
      `cardImages.js` started indexing the same resolved entry under the
      back name too (needed for the toggle below), which would have turned
      that latent miss into a real wrong-art hit. Fixed by making
      `resolveImageUrl` branch on face before trusting the cache hit.
      On top of that fix: a "peek other face" button (`objCard`,
      `.gf-card-flip`) on any permanent with a back face — a client-only
      preview (`flippedForView`, a `Set<instance_id>`, same pattern as
      `attackMenuOpen`) that shows the *other* face's art without touching
      real game state, independent of RULE 712.8's actual `transform`
      action (still offered separately among a card's own action buttons
      when its ability allows it). Needs the backend to say whether a
      permanent has another face at all without guessing from a
      name-keyed cache — `GameObject.to_dict()` gained `has_back_face`
      (backend Done, "Card-type & structural coverage"). `cardImages.js`
      now caches a DFC's resolved entry under both its front and back
      name (pointing at the same entry, plus new `backSmall`/`backNormal`
      URLs) so a transformed permanent's board tile, and its hover tooltip,
      both still resolve correctly by whichever name is currently showing;
      `preloadCardImages` now warms the back-face image too, so flipping
      (or an actual transform) never pops in unloaded art.
      `cardHoverDetail.js`'s tooltip was the other latent front-face-only
      spot: since the cache is now keyed under both names, a hover on a
      transformed permanent would otherwise have silently rendered the
      *front* face's name/type/oracle text/art — `faceForName`/`faceView`
      detect which face is actually being hovered (by comparing the hovered
      name against `card.back_name`) and render that face's own fields,
      plus a small footnote naming the other face. The Replay board
      *editor* (as opposed to its "Spielmodus" play board, which is this
      same shared board) already had its own real, non-preview "Umwandeln"
      transform button, so it didn't need the client-only toggle. Tests:
      `backend/tests/test_card_structures.py`'s `test_has_back_face_*`;
      frontend has no test runner (see CLAUDE.md), validated by reading.

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
      number and current phase/step (German labels), plus a "☀️ Tag"/
      "🌙 Nacht" badge (`.gf-daynight`) once `state.day_night` (RULE 731,
      `docs/implementation-state/BACKLOG.md`/`Done_Backend.md` "Card-type & structural
      coverage") is set — hidden entirely before any daybound/nightbound
      permanent has established a designation, matching the engine's own
      "no designation yet" state.
- [x] Actions shown **directly under the affected cards**
      (`goldfishView.js`, `.gf-card-slot`/`.gf-card-actions`): a hand card
      shows "🌳 Land spielen" / "✨ Zaubern"; a land shows a **tap button
      per mana option** (dual lands get one per colour — the "🟢/🔵" choice
      matching the backend `tap_for_mana` `option_index`). Attacking is a
      **per-creature** "⚔️ Angreifen" button on each attack-eligible card
      (ENG-15/VIS-3, superseding this bullet's earlier aggregate-control
      description) — see `gameBoardView.js`'s dedicated entry below. Built
      from the session's per-object `legal_actions`.
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
- [x] Stack tiles for triggered/activated abilities now show their
      *source permanent's* card art instead of a bare text box
      (`gameBoardView.js`'s `stackItemHtml`, the shared board module
      `goldfishView.js`'s stack display above was later extracted into):
      the ability's description renders as a text banner overlaid on that
      art (`.gf-stack-ability-overlay`), and a small 🔗 `.gf-stack-source-
      link` icon in the corner exposes the same source via the existing
      global name-hover preview (`cardHoverDetail.js`) — driven by the new
      backend `StackItem.source` field (`Done_Backend.md` "Rules Engine").
      Falls back to the pre-existing plain-text tile when there's no
      source or no resolvable art. A code audit confirmed every triggered
      ability (`_collect_triggers`/`put_triggers_on_stack`) and activated
      ability (`GameEngine.activate_ability`, including Equip/Fortify/
      Reconfigure and loyalty abilities) goes through one of these two
      choke points and so is now covered — mana abilities correctly never
      reach the stack at all (RULE 605.1a) and were never meant to be.
- [x] RULE 616.1 replacement-effect ordering popup: the `replacement_
      order` `pending_choice` (`Done_Backend.md` "Rules Engine" —
      "Replacement ordering") gets a dedicated drag-and-drop list
      (`gameBoardView.js`'s `replacementOrderHtml`/
      `confirmReplacementOrder`, `.gf-reorder-list` in `main.css`) instead
      of the generic one-button-per-option modal every other choice kind
      shares — the app's first drag-and-drop UI. Dragging only reorders
      client-side state; confirming replays the chosen order as a
      sequence of the same single `choose` picks the backend already
      expects, stopping the auto-play rather than submitting a stale pick
      if the server's freshly re-offered options ever don't match.
- [x] Generic cast/activate-ability **targeting UI** (RULE 115/601.2c):
      `castTargetHtml`/`castTargetModalHtml` (`gameBoardView.js`) turn any
      `cast_spell`/`activate_ability` legal action with `requires_target`
      into a "→ Ziel ▾" button opening a `.gf-target-modal` that walks
      through each target requirement in turn (multi-target support via
      `reqIndex`), offering `∅ Kein Ziel` when optional, before sending the
      picked `targets`/`x` with the actual action. This single mechanism
      covers spell targeting, Aura casting (an Aura's ETB attach target is
      just its spell target), and Equip/Fortify/Reconfigure (ordinary
      `activate_ability`s with an `AttachEffect`) — no separate "equip
      control" was needed. `attached_to` battlefield grouping
      (`.gf-attach-group`) was already in place from earlier work.
- [x] `pending_choice` modal coverage extended beyond search/cascade/
      discover/replacement-order to the remaining kinds that already rode
      the same generic mechanism server-side but fell back to a plain ❔
      icon: `land_tapped` (shock-land pay-life, RULE 614.1), `trigger_target`
      (a triggered ability's own target/"you may"), `order_triggers`,
      `enter_as_copy`, `counter_unless_pays` all now have a themed
      `CHOICE_ICONS` entry.
- [x] Planeswalker loyalty display (RULE 606): `objCard()` renders a
      dedicated `◆ {loyalty}` badge (`.gf-loyalty-badge`, top-right corner)
      off `GameObject.loyalty`, excluded from the generic counter badge to
      avoid double-showing the same number. Loyalty-ability buttons
      (`[+N]`/`[-N]`/`[0]`, parsed from `cost_label` via
      `loyaltyModifierClass`) get a color-coded modifier class
      (`--ok`/`--error`/`--text-dim` for plus/minus/zero) across all three
      `activate_ability` render paths (plain, X-cost, target-requiring) so
      they read apart from an ordinary activated-ability button at a
      glance — the once-per-turn/sorcery-speed/loyalty-affordability gating
      was already enforced server-side.
- [x] **"Play/cast from the top of your library" visualization**
      (Oracle of Mul Daya/Glarb, Calamity's Augur-shaped — a new backend
      capability, `game/top_library.py`/`Done_Backend.md` "Rules Engine
      (Phase 2)"): the library zone (`gameBoardView.js`'s
      `libraryTopHtml`) renders the top card's face — with whatever
      `play_land`/`cast_spell` buttons `legal_actions` offered for it,
      via the same per-instance `byInstance` mechanism every other zone
      already uses, so a look-only grant (no matching legal action) shows
      the card with no buttons while a play/cast-enabling grant works
      exactly like a hand card — whenever the new `view()` field
      `top_library_visible[player_id]` is true; hidden otherwise (the
      ordinary case). No new component needed: the card's own data was
      already on the wire (`Player.to_dict()`'s `library` array), and
      `objGrid` already builds a card tile with its actions from any
      object list.
- [x] **Per-card effect summary ("Info-Punkt", RULE 613)** — a Σ-badge in
      each battlefield card's top-left corner (`gameBoardView.js`'s
      `effectSummaryHtml`) that opens a native **Popover API** panel (rendered
      in the browser's top layer, so it's never clipped by a card's/row's
      `overflow` nor painted under a later card; positioned at the badge by
      `wireEffectPopovers`) listing every effect currently reshaping that
      permanent — Auren,
      Ausrüstung, statische Anthems, +1/+1-Marken, "bis Zugende"-Buffs — each
      with its **source** and a **duration** chip (`statisch` / `dauerhaft` /
      `bis Zugende`), plus the resulting P/T & keywords as the "Ergebnis"
      (Summe). Built from the object's existing `static_trace`, now enriched
      backend-side: `continuous._trace` tags each entry with a `duration`, and
      a resolved pump/keyword grant records a per-source breakdown
      (`GameObject.temp_effects`, `effects.PumpEffect._pump_one`) so a
      Monstrous Rage / Giant Growth line names its own spell instead of a
      generic "Until-EOT" aggregate. Complements the existing global
      "Statische Effekte"-Panel (`staticEffectsPanelHtml`), which stays.
- [x] **Kicker/Multikicker payment UI (2026-07-20)** — `legal_actions`
      has surfaced `has_kicker`/`kicker_cost`/`kicker_multi`/`max_kicker`
      on a `cast_spell` action since the M2 alt-cost-keywords batch
      (2026-07-15, `Done_Backend.md`), but nothing consumed it: the board
      had no control to pay Kicker, and `services/game_session.py`'s
      `cast_spell` action handler never even read a `kicked` field off the
      wire action, so it couldn't have worked end-to-end regardless. Fixed
      both: `game_session.py` now forwards `kicked = int(action.get(
      "kicked", 0))` to `GameEngine.cast_spell` (mirroring how `x` already
      round-trips); `gameBoardView.js` gained a `kickerFieldHtml`/
      `kickerKey`/`readKicker` trio mirroring the existing `{X}`-cost
      `has_x`/`max_x` treatment exactly (a number input, 0..`max_kicker`,
      defaulting to **0** — unlike X's default-to-max, since paying Kicker
      is an opt-in extra cost) — wired into all three `cast_spell` render
      shapes (plain, `has_x`, `requires_target`) so a kickable+targeted or
      kickable+X spell offers both fields together. Verified with a real
      Playwright run against a live backend (Replay/Puzzle mode, Kavu
      Titan — Kicker `{2}{G}`, "if kicked, enters with three +1/+1
      counters and with trample"): the input rendered, paying it sent
      `kicked: 1`, and the resolved permanent showed a "+1/+1 x3" counter
      badge and a "TR" keyword badge, exercising the new engine-side
      kicked-counters-plus-granted-keyword grammar
      (`parser/oracle/catalogue/counters.py`'s `_GRANT_KEYWORD_SUFFIX`,
      `docs/implementation-state/BACKLOG.md`'s former "Targeting / multi-target /
      counters" chapter, Item F) through the real UI, not just unit
      tests. Buyback (`has_buyback`/`buyback_cost`) is a separate,
      still-open gap — `docs/implementation-state/BACKLOG.md` "Buyback alt-cost". Tests:
      `test_game_session.py::TestStackAndChoices::
      test_cast_spell_forwards_kicked_to_the_engine`.
- [x] **"Castable from exile" zone (2026-07-20)** — the engine already
      tracked three distinct persistent "you may cast this from exile"
      states (impulsive draw's turn-scoped `GameState.
      temp_play_permissions`; Adventure's `GameObject.adventure_castable`;
      Prepared's `prepared_source_id`) but nothing on the board surfaced
      them together, so a castable exiled card was invisible unless the
      player already knew to look. Added a prominent "🎇 Spielbar aus dem
      Exil" panel (`gameBoardView.js`'s `exileCastableInfo`/
      `exileCastableHtml`), inserted between the static-effects panel and
      the Hand zone — mirroring `libraryTopHtml`'s "additive, not replacing
      the ordinary zone" precedent — listing every exile object any of the
      three mechanisms currently allows, each rendered with the existing
      `objCard`/action-button machinery (so its cast button is the same
      live one Hand/Battlefield use) plus a caption naming the **source**
      and **duration**: Adventure → "Adventure — eigene Zauberspruch-Hälfte
      bereits gecastet" / "kein Zeitlimit (bis gezaubert)"; Prepared →
      names the linked permanent / "solange die Quelle 'gewappnet' ist";
      impulsive draw → the spell name that exiled it (new backend-side
      `GameState.temp_play_permission_source: dict[instance_id, str]`, a
      parallel dict to `temp_play_permissions` rather than widening its
      value type, populated by `RulesEngine.exile_with_play_permission`'s
      new `source_name` param and pruned in lockstep by `_step_cleanup`) /
      "bis Ende des nächsten eigenen Zugs" (this turn) or "bis Ende dieses
      Zugs" (granted last turn). Cascade/Discover deliberately excluded —
      those resolve synchronously via `pending_choice`, never sitting in
      exile waiting to be cast. Also added a `prepared_copy` bool to
      `GameObject.to_dict()` (was missing — only the source-side `prepared`
      flag existed) and a matching `preparedCopyBadge` overlay
      (`objCard`), plus `.gf-exile-castable`/`-entry`/`-caption` CSS.
      Verified with a real Playwright run against a live backend
      (Replay/Puzzle mode, Bonecrusher Giant // Stomp): cast Stomp from
      hand → the creature half appeared in the new zone with the Adventure
      caption → cast it from there → the zone emptied and Bonecrusher
      Giant landed on the battlefield, all with zero page errors. Tests:
      `test_impulsive_draw.py`'s new "temp_play_permission_source" section
      (4 tests) and `test_card_structures.py::
      test_prepared_copy_is_serialized_for_the_board_but_an_ordinary_object_is_not`.
- [x] "Planned" RULE 603.7 delayed-trigger panel (`gameBoardView.js`'s
      `delayedTriggersPanelHtml`): a compact, always-visible-when-non-empty
      list — thumbnail (`resolveImageUrl`, reusing the Stack overlay's own
      art-resolution) + description + a "⏳ Zu Beginn von …" timing line
      (`delayedTriggerWhenLabel`, `scope: "controller"` names the player,
      `"any"` reads "des nächsten Schritts" — gender-neutral phrasing since
      the step names don't share a grammatical gender) — reading a new
      `GameSession.view()` key, `delayed_triggers`
      (`GameState.delayed_triggers` mapped through a new
      `DelayedTrigger.to_dict()`). Backend-side, `CreateDelayedTriggerEffect`
      gained a real `description` param (previously always blank —
      `getattr(self, "description", "")` read an attribute nothing ever
      set) now filled in for both existing users (Mana Drain, Final
      Fortune) plus three new showcase cards built specifically to exercise
      this panel: Ephemerate's Rebound (RULE 702.88b — exile-on-resolve +
      a same-turn free-cast window reopened at the next upkeep, `AbilitySpec.
      rebound`/`ReboundFreeCastWindowEffect`/`GameState.
      free_cast_instance_ids`), Marchesa, the Black Rose's counter-death
      return trigger (`AbilitySpec.counter_death_return`/
      `RulesEngine._collect_counter_death_return_triggers`/
      `MarchesaDelayedReturnEffect` — Dethrone itself stays unmodeled, see
      `docs/implementation-state/BACKLOG.md`), and Sneak Attack/Meek Attack's cheat-
      into-play-then-sacrifice (`CheatCreatureFromHandEffect`/
      `SacrificeObjectEffect`, `RulesEngine.put_hand_creature_onto_
      battlefield`). Verified end to end against a live backend over the
      real HTTP API (curl — no Playwright/browser tool available this
      session, so no pixel-level screenshot): casting Ephemerate correctly
      armed the delayed trigger, advancing to the next upkeep opened the
      free-cast window, and casting it from there with an empty mana pool
      resolved it to the graveyard without re-arming Rebound. That same
      pass caught and fixed two real pre-existing bugs, unrelated to this
      panel itself: `RulesEngine.blink` left a phantom duplicate reference
      in the owner's exile zone list after returning the blinked object to
      the battlefield (`_put_searched_card`'s battlefield branch never
      removes the object from wherever it currently sits — its other
      callers already pop the card off its zone first, `blink` didn't); and
      `GameEngine.legal_actions`'s exile loop only ever checked
      `_castable_from_exile` (the Adventure/prepared-copy shapes), so a
      temp-play-permission-exiled card (Light Up the Stage/Ragavan/
      Mnemonic Betrayal/Rebound alike) could never actually be offered as a
      castable action at all, despite `can_cast`/`cast_spell` fully
      supporting it — no prior test caught either gap because every
      existing impulsive-draw test asserted `can_cast` directly instead of
      going through `legal_actions`, the actual surface any real caller
      uses. Tests: `backend/tests/test_delayed_trigger_examples.py` (18
      tests).
- [x] Four remaining backend-ready "Game engine hookup" gaps wired up in one
      pass (2026-07-21), each previously plumbed server-side with no UI:
  - **Restricted-mana display** (RULE 605.3a "Spend this mana only to cast
    a creature spell"): `manaPoolHtml`'s new `restrictedManaHtml` renders
    each of `Player.mana_pool.restricted`'s lots as its own 🔒-badged span
    (`.gf-mana-restricted`), never merged with the ordinary WUBRGC counts
    it isn't merged with server-side either. A `restrictionLabel` maps the
    opaque `restriction.kind` dict (`contains_x`/`creature_spell`/
    `commander_spell`/`legendary_spell`/`instant_or_sorcery_spell`/
    `type_spell`, `game/mana_abilities.py`'s `_parse_restriction`
    whitelist) to a German tooltip, since there's no server-side label
    string for this the way `TargetSpec.label()` covers targets.
  - **"Any combination of colours" split builder** (RULE 605.1a —
    Flamebraider/Gwenna/Smokebraider/Selvala): `colorSplitHtml` adds a
    5-input (WUBRG, never colourless) builder alongside the pre-existing
    single-colour buttons whenever a `tap_for_mana`/`activate_hand_mana`
    action carries `any_combination`/`combination_total`; a client-side
    sum check against `combination_total` (mirroring the server's own
    `validate_color_split`) catches a mis-filled split before the round
    trip, then sends `color_split`.
  - **Hand-zone mana ability trigger** ("Exile this card from your hand:
    Add …", RULE 605.1a — Elvish/Simian Spirit Guide): `cardActionButtons`
    gained an `activate_hand_mana` branch (previously unhandled — the
    action was already reaching the per-card button list via `byInstance`
    but nothing rendered it), showing a "📤 `cost_label` → mana" button per
    option, plus the same split builder above when applicable.
  - **"May choose not to untap" toggle** (RULE 502.1 — Rubinia
    Soulsinger/Hivis of the Scale/The Pandorica-shaped): `legal_actions`
    (`game_engine.py`) previously had *no* offer for this at all, despite
    the engine method (`set_skip_untap`) and dispatch
    (`services/game_session.py`) already existing — a new per-permanent
    loop now emits `{"type": "set_skip_untap", "instance_id", "name",
    "skip_untap"}` for every permanent with `continuous.
    has_optional_no_untap_permission`, and `cardActionButtons`'s new
    branch renders it as a sticky toggle button reflecting the current
    state (`.gf-card-action--skip-untap-on` when on). Backend test:
    `test_legal_actions_offers_set_skip_untap_only_with_the_permission`
    (`tests/test_batch8_permission_statics_family.py`). **Coverage note**:
    verified live (Playwright) against real cards for the first three —
    Castle Garenbrig (restricted mana), Selvala, Heart of the Wilds (any
    combination), Simian Spirit Guide (hand mana) — but every one of the
    ~46 *real* cards with the "may choose not to untap" clause pairs it
    with a second, still-unmodeled clause (a lock-down/gain-control
    effect), so the oracle parser's fail-closed whole-card gate never
    binds it on a real card today; verified instead with a synthetic
    single-ability token (`type_line: "Artifact"`, `oracle_text: "You may
    choose not to untap ~ during your untap step."`) built in Replay/
    Puzzle mode, which does reach `MODELED` and exercises the real
    bind-on-load path end-to-end. Tracked as its own backend gap in
    `docs/implementation-state/BACKLOG.md` "Game Engine (Phase 3)".
  - The fourth item on the original list, "up to one target" decline, was
    already shipped (see the generic targeting UI entry above,
    "offering `∅ Kein Ziel` when optional") — the `frontend/ToDo_
    Frontend.md` entry describing it as open was stale.

- [x] **Face-down permanents, dungeons and Planechase on the board**
      (2026-07-28, the frontend half of the RULE 708/309/901 backend work —
      `backend` worklog "Face-down spells and permanents", "Dungeons",
      "Formats and casual variants").
  - `resolveImageUrl` now renders the player's chosen **card-back sleeve**
    for a face-down permanent. That fallback had existed since the sleeve
    feature shipped but was unreachable: the only state that could hit it
    was a face-down *token*, which nothing could produce. Nothing is hidden
    client-side — the backend ships only the synthetic 2/2 face (RULE
    708.2a), so the identity isn't in the payload for any viewer.
  - A `🎭` badge names *why* a permanent is face down (Morph / Verkleidung /
    Manifestiert / Verhüllt), which is what decides how it can be turned up
    and whether it has ward {2}. Bottom-left — the one corner the attacking/
    loyalty/counter/keyword badges don't already use, since a face-down
    creature can be attacking and carrying counters at the same time.
  - `🔎 Aufdecken (<Kosten>)` is offered per payable route, straight from
    `legal_actions` — a manifested morph card genuinely offers two (RULE
    701.40c), so this is a button per option, not a single toggle.
  - The player-counter strip gained the command-zone facts that have no
    card tile of their own: the dungeon and its current room (with the
    room's own effect text in the tooltip), completed dungeons, a Vanguard
    avatar, the archenemy's scheme count, and any face-up ongoing scheme.
  - Planechase gets a strip of its own above the boards: the face-up plane
    and the `🎲 Planarwürfel` special action with its live {X} cost. It
    renders nothing at all when there's no planar deck, i.e. in every game
    that isn't Planechase. Deliberately no `data-hover-card` on the plane
    name — planes aren't in the card cache at all (the bulk importer drops
    the `planar` layout), so a hover lookup by name could only ever miss.

- [x] **Targeting rounds now report which requirement each pick belongs to**
      (MEC-10, 2026-07-28). The modal already walked a spell/ability's
      requirements one at a time (`expandMultiTargetRequirements`), but it
      only ever posted the picks as one **flat** list. That is enough while
      every effect wants the same target, and wrong the moment two clauses
      want different ones — "Target creature you control gets +1/+2 until
      end of turn. It fights target creature you don't control." would pump
      and fight the same creature. Each expanded round now remembers the
      index of the requirement it came from (`owners`), picks accumulate
      into per-requirement `groups`, and a cast/activate with 2+
      requirements sends `target_groups` alongside the flat `targets` (which
      ward, the stack display and every other consumer still read).
      The flat list stays the wire default for the single-requirement case,
      and the server derives the partition itself when it's unambiguous
      (`targeting.partition_targets`) — but only the client can express a
      **declined** "∅ Kein Ziel" on an "up to one", since a shorter flat
      list can't say *which* slot is empty. That's the whole reason the
      groups are sent rather than re-derived.
      Same modal, one new exclusion: a requirement flagged
      `distinct_from_others` (RULE 109.5's "**another** target creature" —
      Pit Fight, Ulvenwald Tracker) drops everything already picked in an
      earlier round from its pool, exactly as `excludePicked` does within a
      single "pick N" requirement.

## Multiplayer

- [x] **The Multiplayer tab is two tabs**, "Setup" and "Board", driven by
      one persistent controller (`multiplayerView.js`) the way Goldfisch
      and Replay each have one. "Board" is `disabled` in `index.html` and
      only unblocked (via app.js's `onBoardAvailable` hook) once this
      client is actually at a table — there is nothing to render without a
      game, and a dead tab you can click into is worse than one you can't.

      **Setup** is the lobby: every connected player with their presence
      state (🟡 Online / 🟢 Verfügbar / 🔵 Im Spiel), every table with its
      seats and status, a "Spiel erstellen" box, and — once you're at a
      table — the seat panel: who sits where, each seat's deck, the
      host-only Mulligan-Regel dropdown, an "✔ Bereit" toggle per player
      and the host's "▶ Spiel starten". Any change to the table (a deck
      pick, a join, a settings change) clears everyone's acceptance
      server-side, and the panel re-renders from the push, so you can never
      be carried into a game you didn't agree to.

      **Board** is the shared `gameBoardView.js` — the same board the other
      two modes drive — with three things wired in for a shared game: a
      multiplayer *transport* (each action is attributed to this seat and
      the board repaints from the socket push, not the HTTP reply, so both
      screens update from the same message); your own seat drawn *last*
      (nearest you, opponents above) with "Du"/"am Zug"/"aufgegeben"
      badges; and 🏳️ Aufgeben in place of Zurücknehmen/Nächste
      Entscheidung, which are solo-practice affordances that make no sense
      at a shared table. Mulligan is this module's own screen (each seat
      mulligans in parallel and then sees who the table is still waiting
      for); the end-of-game review reuses the Goldfisch stats digest,
      extracted for the purpose into `gameStats.js`.

- [x] **An opponent's hand renders as card backs.** The count comes from
      `hand_count`, the contents never arrive at all (the server redacts
      them — RULE 400.2), and the back is the player's own uploaded sleeve
      if they have one. Same path draws an observer's view of *both*
      hands.

- [x] **Beobachter-Modus**: "👁️ Zuschauen" on any running table. The board
      renders with no hands, no game controls and a banner saying so; the
      only button is "Zuschauen beenden".

- [x] **Blocker-Deklaration** (RULE 509.1a) — the first interactive
      combat UI on the defending side. One row per creature that could
      block, each with a dropdown of the attackers it may legally be
      assigned to; picks accumulate in a local draft and "Block
      bestätigen" submits the *whole* block as one action, which is what
      makes Bedrohlich/menace (RULE 702.111b, validated across the
      complete assignment) satisfiable at all. Shared code, so Replay's
      play mode gets it too.

- [x] **VIS-3 · Per-creature attacker selection UI (`gameBoardView.js`'s
      `attackControlHtml`) — closed, no new work needed.** Each
      attack-eligible card already renders its own "⚔️ Angreifen" button
      rather than one aggregate "swing with everybody" control: with zero
      or one legal defender it's a single click, and with 2+ (a 3+ player
      pod, or a battle/planeswalker on the board) it opens a per-defender
      menu, one `declare_attackers` action per creature — matching the
      backend's additive `declare_attackers` (ENG-15, `Done_Backend.md`).
      `BACKLOG.md` still described the board's original goldfish-only
      aggregate control, superseded when this shared board (Replay +
      Multiplayer) needed per-attacker defender choice; the entry was never
      re-checked afterward. Nothing left to build — the paired bullet above
      this file's "Actions shown directly under the affected cards" entry
      has been corrected to match.

- [x] **Priority is visible and interactive** (RULE 117). In a shared game
      the toolbar swaps "Nächster Schritt" for **"Passen"** — a step ends
      when everyone passes, so there is deliberately nothing to press that
      *advances* it — plus a badge saying either "Du bist dran (Priorität)"
      or "⏳ X ist dran …". Everything else is disabled while it isn't your
      window, which matches what the server will accept.

- [x] **Auto-pass with a countdown.** When this client holds priority a
      timer runs and passes at zero, so a game where nobody wants to
      respond doesn't need two clicks per step. Deliberately not silent:
      the remaining seconds tick down on the badge, and **any interaction
      with the board cancels that window** (the number is struck through)
      — it must not be able to pass out from under someone mid-decision.
      Default on, 3 seconds, and scoped to *opponents' turns only*, which
      is what auto-pass means in every Magic client and keeps your own turn
      entirely under your control; "alle Züge" is available for players who
      want a fixed pace throughout. Set in **Einstellungen** and adjustable
      on the board itself mid-game (both write the same cookies), because
      people change their mind about auto-pass exactly when it has just
      cost them a response.

- [x] **Reconnect keeps your seat.** The lobby socket reclaims by *player
      name* (the Profil tab), so a page reload or a dropped connection
      lands you back in the same game rather than as a new player. The
      board is rebuilt from the server's push, and the reason the server
      dropped you (`idle` / `replaced` / `timeout`) is shown in words
      instead of the UI silently flickering. A player whose connection went
      away is badged **⚡ getrennt** on their own board (connection state is
      lobby data, so it reaches `gameBoardView.js` through a `seatStatus`
      hook rather than through the `GameState`), which is the explanation
      for why the server is passing priority for them.

- [x] **`lobbySocket.js`** — the `/ws/lobby` client: presence signal,
      lobby snapshots, per-seat board pushes, peer connect/disconnect
      events, and reconnect backoff that reclaims the seat by name.

- [x] **Board polish pass (2026-07-27).** Six things a real two-player
      session made obvious, all in `gameBoardView.js` unless noted:

      - **An opponent's hand is a number, not a row of card backs**
        (default; `settings.js`'s `showOpponentHand`, toggleable on the
        hand zone itself and in Einstellungen). The cards were never on the
        wire — RULE 400.2 redaction happens server-side — so the backs were
        pure decoration costing a lot of vertical space on a two-board
        screen. Cards that *are* in an opponent's `hand` array (i.e. ones
        the server chose to reveal) are always drawn, whatever the toggle
        says. Only offered where there *is* an opponent: a Replay/Puzzle
        board has no perspective and both hands stay visible, since editing
        them is the whole point of that mode.
      - **⏭ Nächste Aktion** — the shared-game answer to goldfish's
        "Nächste Entscheidung", which multiplayer can't have (skipping
        *steps* would skip the opponent's response windows). This one only
        passes priority, and only through windows where `legal_actions`
        offers literally nothing but `pass_priority`, stopping at the first
        window that actually asks something. A persisted checkbox
        (`autoSkipEmpty`) arms it permanently. Deliberately separate from
        auto-pass: auto-pass is an interruptible countdown *because* there
        was something you could have done, and an empty window has nothing
        to interrupt.
      - **The pass button and the priority badge are repeated on your own
        board's banner.** With two full boards drawn, the toolbar at the
        top of the page is usually scrolled off exactly when you need it.
        Same control, so it's `data-pass-priority` rather than an id, and
        every instance is wired.
      - **"Zug N" is now the round**, not the raw per-player turn count
        (`GameState.round_number`, see `Done_Backend.md`). The rules-correct
        number is still there, in the tooltip.
      - **Player-level counters are drawn at last**: poison (RULE 704.5c,
        badged as lethal at 10), the counter bag (RULE 122 energy,
        experience, rad, …), the Ring's level (RULE 701.52), the Monarch
        and Initiative designations (RULE 725/726) and emblems (RULE 114).
        Every one of them was already in the payload and simply never
        rendered — only life and the mana pool were.

- [x] **Board polish follow-up (2026-07-27), four bugs a real session
      surfaced in the pass above:**

      - **"Blockt nicht" is now a submittable answer.** The block panel's
        confirm button required at least one assignment (`blockDraft.size
        > 0`), so a defending player who wanted to decline every block had
        no way to *confirm* that — RULE 509.1a's "declare no blocks" is a
        real, complete turn-based action, not the mere absence of one.
        `submitBlocks` now sends an empty `assignments: []` (the backend
        already accepted it; only the client refused to send it), and the
        button reads "Keine Blocker bestätigen" when nothing is selected.
      - **Equip/Fortify/Reconfigure were legal onto *any* creature/land,
        including an opponent's** (`game/targeting.py`'s `legal_targets` and
        `game/rules_engine.py`'s `_attachment_legal`, both offer-time and
        resolution-time) — RULE 702.6a/702.67a/702.151a all say "target
        creature/land *you control*", which nothing was checking. Fixed at
        both points (backend-only; no frontend change), with regression
        tests seating an opponent's creature/land as bait.
      - **"Leere Fenster überspringen" could spam the server with redundant
        `pass_priority` calls fast enough to make casting feel broken.**
        Root cause: the multiplayer transport deliberately returns no fresh
        `data` from `act()` (it waits for the socket push instead — see the
        transport's own comment in `multiplayerView.js`), so `view` — and
        the priority-window key derived from it — can stay unchanged across
        several renders while a pass is still in flight to the server and
        back. `skipEmptyArmed()` had no memory of having already tried a
        given window, so every one of those renders fired another attempt,
        as fast as the event loop allowed, tearing the board down under any
        click the player was making. Fixed with a `skipAttemptedForKey`
        latch mirroring auto-pass's own `autoPassWindowKey` bookkeeping — at
        most one attempt per distinct window, then genuinely wait. Verified
        with a `jsc`-driven headless harness (the project has no JS test
        runner and `osascript -l JavaScript` doesn't drain microtasks
        between statements, so a real event-loop-bearing engine was needed
        to reproduce the runaway): the pre-fix code hit >20 calls before the
        harness's own safety cap; the fix holds it to exactly one. Both
        checkboxes' tooltips were also rewritten in plain language after the
        session reported not understanding what the label meant.
      - **Turn/phase is now sticky and one row.** `.gf-topbar` scrolled out
        of view on a two-board screen (exactly when you most want to check
        the step); it's `position: sticky; top: 0` now (below the stack
        overlay's z-index, so a resolving stack still visually covers it).
        `.gf-turninfo` switched from a vertical stack to a wrapping row —
        turn, phase/step, active player and day/night now sit side by side.

- [x] **A finished game is closed deliberately** (`multiplayerView.js`):
      the digest no longer hijacks the board irreversibly — "🔍 Spielfeld
      ansehen" flips back to the final position, "📊 Auswertung" flips
      back, and "✖ Spiel schließen" ends the table. Leaving a *finished*
      table now really leaves it (backend half in `Done_Backend.md`),
      so the last player out takes the dead row out of everyone's lobby
      list with them.

- [x] **Bot seats (UC5, 2026-07-27).** The host can fill a free seat with
      a bot from the Setup panel: a kind picker (`GET
      /api/multiplayer/bots`, so the list is the server's, not a hard-coded
      one) whose hint line describes the selected bot, and a 🤖 Hinzufügen
      button. A bot seat renders in the same seat list as everyone else,
      marked 🤖 with a dashed border, and — for the host, before the game
      starts — carries the two controls a bot can't operate for itself: an
      inline deck `<select>` (posting `seatId`, the one case where a player
      picks a deck for a seat that isn't theirs) and an ✕ to take it back
      off the table. Everything after that is unchanged, because a bot is
      an ordinary seat: it shows as ✔ bereit once it has a deck, the table
      starts the usual way, and its turns arrive as ordinary pushed views.

- [x] **Per-seat take-backs (UC4 Setup, 2026-07-27).** A table-configured,
      rules-free undo budget — a "Take-backs je Spieler" number field in
      the Setup panel (host only, 0 by default), and, once the game is
      running, a "↩️ Zug zurücknehmen (N)" button next to "Aufgeben"
      showing the caller's own remaining count and disabled at 0 or when
      the table was set up with none at all (`view.takebacks_remaining`
      being an empty object). See `Done_Backend.md`'s `GameSession.
      take_back` for the shared-timeline semantics (undoing your own last
      move undoes anything an opponent did since, too — there's only one
      history to restore) — the button's tooltip says so plainly, since
      "why did my opponent's move also disappear" is the one thing about
      this feature that isn't obvious from the label.

- [x] **Pod-sized tables, 2–4 seats (PLR-2, 2026-07-28).** Two controls and
      one board affordance. In Setup, the "Spiel erstellen" row gained a
      seat-count `<select>` (2/3/4, passed as `numPlayers` — `api.js` had
      always taken the argument, nothing ever sent it) and the table panel
      gained a host-only "Plätze" row that can still be changed until the
      game starts. Counts below the number of players already seated are
      `disabled` rather than hidden, so it's visible *why* a table can't
      shrink further; the server clamps the same way regardless. The
      "Aktuell werden zwei Spieler unterstützt" hint is gone.

      On the board (`gameBoardView.js`), each opponent's section gained a
      ▾/▸ fold button — offered **only** when there are 2+ opponents,
      since with one there is nothing to scroll past. Folding hides the
      play area and leaves the header (name, badges, life, counters,
      priority) plus a one-line count summary (permanents/creatures/hand/
      library/graveyard/exile). Nothing is folded by default: hiding an
      opponent's board by default would hide the thing you most need to
      look at. It's pure client-side view state (`collapsedBoards`), not
      persisted — and no information question arises either way, since the
      counts it shows are what the board prints anyway and the hidden
      zones behind them never left the server (RULE 400.2).

- [x] **2x2 pod layout + inside/outside zone columns (2026-07-28).**
      Folding an opponent away made a 3–4 seat table survivable; it didn't
      make it readable. From **three live boards up**, `gameBoardView.js`
      wraps them in a `.gf-pod-grid` (`boardsHtml`) that tiles two per row
      instead of stacking, so no seat is below the fold. DOM order is
      untouched — opponents first, this client's seat last — so the grid
      fills row-major and "drawn last is nearest you" still holds. At three
      seats the odd board out is by definition that last one, i.e. your
      own, and it takes the whole bottom row (`:last-child:nth-child(odd)`)
      rather than half of it: it's the board you actually play from. Four
      seats is a plain 2x2. Not a preference and not persisted — it's a
      consequence of how many people are at the table. Observers get it
      too, hence keying off the live-player count rather than
      `view.perspective`.

      The existing "⇄ Zonen-Seite" toggle doesn't survive the transposition:
      one fixed side puts one column's zones against the screen edge and the
      other's in the middle of the screen. In the grid it therefore becomes
      **innen/außen** (`zonesInside`, cookie `gf_zones_pod`, persisted
      separately from `gf_zones_side` because the two describe different
      layouts and a player wants both remembered), and `zonesSideFor(index)`
      mirrors the columns so the word means the same thing on both sides.
      Default *außen*: the zone columns hug the outer edges and the
      battlefields face each other in the middle — the physical table it
      models, and it puts the two things you compare next to each other. One
      button either way (its three copies across the observer/priority/plain
      toolbars are now one `zonesSideButtonHtml`), reading out the current
      state in grid mode since which of two mirrored layouts you're in isn't
      obvious at a glance.

      Seats are placed **clockwise**, not in auto-placement's reading order.
      Row-major fill puts the third board bottom-*left*, which runs the ring
      backwards across the bottom row and leaves seat 4 next to seat 3 twice
      over; explicit `grid-area` per `nth-child` gives 1=top-left,
      2=top-right, 3=bottom-right, 4=bottom-left, so turn order goes round
      the table and the last seat is back beside the first. The three-seat
      full-width bottom row still wins its column back — it carries one more
      pseudo-class than the placement rules, so specificity settles it
      without an `!important`. `gameBoardView.js`'s `POD_COLUMNS` mirrors
      the mapping (the zone-side toggle needs to know which column a board
      is in, and it is deliberately *not* `index % 2` any more); the two
      have to be changed together, and both say so.

      The boards are ordered by **turn order** rather than by seat-list
      position (`boardOrder`). `GameState.players` already *is* the turn
      order — `next_active_index` walks it cyclically (RULE 500.1), skipping
      dummies and players who have left (RULE 104.3a) — so this is a
      *rotation* of that list, not a sort: rotating keeps the cycle intact
      while preserving the older rule that your own board comes last, i.e.
      nearest you. Reading the grid row-major then goes around the table the
      way the turns do, first board = whoever plays after you. Without a
      seat (solo modes, observers) there's nothing to rotate to and the
      plain turn order stands.

      The topbar gained the matching **turn-order strip** (`turnOrderHtml`),
      which replaced the older "Aktiv: X" readout — same information plus
      who is up *after* them. It's in board order rather than
      active-player-first on purpose: it's a legend for the layout below,
      and the two have to read as one statement (a strip that re-sorts every
      turn is also harder to follow than a fixed seating chart). The active
      seat is marked ▶ and accented, your own stays legible when it isn't
      active, and a player who has left is struck through rather than
      dropped — the seating didn't change, the turn just passes over them
      now. Note the CSS declaration order: `-me` and `-active` can land on
      the same seat with equal specificity, so `-active` has to come second
      to win the colour.

      The board banner was rebalanced in the same pass. "Passen" had been
      pushed to the far right of your own board's header (`.gf-banner-
      priority`'s `margin-left: auto`), which is exactly where every *other*
      seat's header shows life — so your own banner read differently from
      the three around it. The priority controls now sit directly beside
      the name and mana/life/counters moved into a `.gf-banner-stats`
      wrapper that owns the auto margin instead (previously it lived on
      `.gf-manapool`, i.e. on whichever of the three came first, which is
      why grouping them was needed at all). "⏭ Nächste Aktion" joined
      "Passen" there, and in doing so had to stop being an `id`: it is now
      drawn twice (toolbar + banner), so it became `[data-skip-empty]` and
      `wire()` binds all of them — the same reason `passButtonHtml` has
      always been a data attribute.

      The narrow-screen fallback is **JS, not a media query**: `podGrid()`
      consults a `matchMedia(min-width: 1200px)` and simply doesn't emit the
      wrapper below it, repainting on the `change` event. Doing it in CSS
      would have left the toggle claiming "innen/außen" while the columns it
      refers to no longer existed — the breakpoint has to be one fact, and
      main.css carries a comment saying where it lives.

- [x] **Vancouver mulligan + the scry that makes it real (PLR-1,
      2026-07-28).** The board needed nothing new for the scry itself: it
      arrives as an ordinary `pending_choice`, so `simpleChoiceButtonsHtml`
      renders "put this one on the bottom" / "Rest oben lassen" as buttons
      and the modal already knows how to be answered — only a 🔮
      `CHOICE_ICONS` entry was added. It lands on the *board* rather than
      in the mulligan screen because the scry happens after the whole
      table has kept, at which point setup is over (see `Done_Backend.md`).

      The mulligan screens did need work, because Vancouver is the first
      style whose hand *shrinks*: the "Mulligan (neue 7 ziehen)" button now
      reads the real number (`setup.next_hand_size`, new in the view), and
      the explanatory sentence — which differs per style and was already
      duplicated between `goldfishView.js` and `multiplayerView.js` — moved
      into a new shared `mulligan.js` (`mulliganText`, plus `MULLIGAN_LABELS`
      and `SEAT_COUNTS`) rather than being forked a third way. The Setup
      tab's Mulligan-Regel dropdown picks the new style up automatically,
      being generated from `MULLIGAN_LABELS`.

- [x] **Banner colours per seat (2026-07-28).** A seat picks the colours
      its board title bar is painted in, so at a pod of four you find your
      own board — and everyone else's — by colour rather than by reading
      four names. The new `bannerColors.js` owns the palette; the board
      (`gameBoardView.js`) and the Setup seat list (`multiplayerView.js`)
      both draw from it, and the backend stores nothing but the key
      (`Seat.banner_color`, see `Done_Backend.md`).

      **The 32 combinations are derived, not enumerated.** A banner colour
      is a *set* of the five colours (any subset, so a deck's whole colour
      identity can be flown) or none of them for grey/colourless — which
      as CSS would be 32 classes. Instead each colour carries two hexes, a
      deep one for the bar and a bright one for a hairline strip along its
      top edge, and `bannerStyle()` hands the two `linear-gradient`s to CSS
      as `--banner-bg`/`--banner-strip` custom properties: **one** rule
      (`.gf-banner-tinted`) draws every banner there can be. A single
      colour still gets a gradient (to a darkened copy of itself) so one-
      and five-colour banners have the same sheen rather than one looking
      flat. The hues are the existing `.color-pip--*` deck-identity
      pastels taken down to the dark theme's lightness, so a Simic banner
      and a Simic pip read as the same green-blue; deep enough that the
      light board text stays legible on all 32, with the `h3` dropping the
      gold `--accent` for near-white plus a shadow (gold is unreadable on
      half the palette). A seat with no colour falls back to the plain felt
      header, which is what every solo mode keeps — Goldfisch and Replay
      have no lobby and so no banner.

      The picker is **five toggles, not a list of 32 named options**,
      because a banner colour *is* a set: turning them all off is how you
      fly the grey banner, which is why there's no separate "grau" button.
      It unfolds from a chip in the seat row (the chip being the very same
      gradient at thumbnail size, so what you pick is literally what you
      get), and every click posts straight through rather than staging
      locally — it can't be wrong, and the others watch the colour appear
      while you're still choosing. A seat with no colour yet shows a
      hatched placeholder, so "not set" doesn't read as "colourless"
      (which is a real choice). The turn-order strip repeats each seat's
      colour as a dot, so it's a legend for the colours as well as the
      order.

      Two smaller things fell out of it: `seatStatus(id)` — the existing
      hook for lobby-side facts the `GameState` doesn't carry — grew
      `banner_color` alongside `connected`, and had to start looking up
      `game.seats` as well as `lobby.players`, since a **bot** has a seat
      but no entry in the connected-players list; and `.mp-seat` became
      `flex-wrap: wrap` so the picker unfolds onto a second line of the row
      it belongs to.

- [x] **PLR-10 · "Save as Replay" on the Multiplayer board (2026-08-04).**
      Scoped down, per explicit instruction, to exactly what "Game
      history / session persistence" needed to unblock: port
      goldfishView.js's existing "⬇ Als Replay speichern" button (it
      already hits the generic `GET /api/game/{id}/replay-export` —
      confirmed no mode check, so a Multiplayer session exported exactly
      like a goldfish one already would) to `multiplayerView.js`'s
      `seatControls()`, in both the normal in-progress array (next to
      Aufgeben/takeback) and the `game_over` one (next to
      Auswertung/Spiel schließen) — so a shared table's position can be
      downloaded and reopened in the Replay tab whether the game is still
      running or just ended. Not offered to observers, matching "it's
      your board" the same way goldfish frames it. No backend change.
      Verified live: created a 2-seat table across two browser contexts,
      started the game, clicked the button and got a real `replay.json`
      download.

- [x] **PLR-6 · Draft persistence, frontend half (2026-08-04).** See the
      matching Done_Backend.md entry for the backend half
      (`GameSession._ui_drafts`/`set_ui_draft`, `POST .../ui-draft`) and
      the root cause it fixes. `gameBoardView.js`'s `applyView` used to
      unconditionally null out `blockDraft`/`castTargeting` on *every*
      fresh view; it now only does that when `move_log.length` (or the
      session id) actually changed since the last view it invalidated
      against, so a view that merely arrived — another seat's socket
      reconnecting rebroadcasts the same committed position to the whole
      table — no longer wipes an unrelated player's in-progress pick.
      Both drafts are also now mirrored to the new endpoint as they're
      built (after every `blockDraft.set`/`.delete`/clear; after every
      cast-targeting start/pick/cancel, funneled through the existing
      `finishCastIfReady`) and best-effort rehydrated in `start()` from
      `view.ui_draft` — a block draft only restores pairings still
      offered in fresh `legal_actions`; a cast/activate draft only
      restores if the same action is still found with a same-shape
      target requirement list. Anything that doesn't line up is silently
      dropped rather than risking a confusing half-restored modal — the
      eventual submit, if any, is still fully validated server-side
      regardless. Fire-and-forget throughout (a failed draft save is a
      worse reconnect experience, never a broken game).

## Replay/Puzzle mode

- [x] **3-4 player pods (2026-08-04).** Backend half (lifting `blank_
      replay`'s 2-player cap) in Done_Backend.md. Two more start-screen
      buttons (`data-start="3"`/`"4"`) in `replayView.js`'s `renderStart`.
      Play mode needed nothing — it's the same `gameBoardView.js` board
      Multiplayer already pods at 3-4 seats (`podGrid()`/`.gf-pod-grid`,
      driven purely by `state.players.length`, no Multiplayer-specific
      dependency). The **editor** (`renderEditor`/`renderPlayer`, its own
      `.replay-players` grid — a from-scratch board-construction UI with
      inline edit affordances gameBoardView.js has no hook for, so full
      reuse wasn't in scope) got a `pod` modifier class alongside the
      existing `two`, with CSS in `main.css` mirroring — same clockwise
      placement, same odd-seat-spans-the-row rule, same `minmax(0, 1fr)`
      reasoning, same narrow-screen fallback breakpoint — `gameBoardView.
      js`'s `.gf-pod-grid` rather than sharing the class outright (`.
      replay-player`'s box styling has nothing to do with `.gf-player-
      board`'s). Verified live: a 4-player puzzle's editor tiled 2x2 in
      the expected clockwise order, and its play-mode board did too, with
      zero console errors either screen.

## Deck analysis (UC2)

- [x] "Deck analysieren" (`analyzeView.js` + `deckAnalysis.js`) is a full,
      **local/static** analysis of a saved deck — no backend call, no AI:
      pure functions over the same resolved `Card` data every other view
      already fetches (`cardImages.js`'s resolve cache), classifying cards
      by regexing `oracle_text` as a **display heuristic only** (a wrong
      guess mislabels a chart; it can never affect actual game behaviour —
      see `deckAnalysis.js`'s header comment for the boundary vs. the
      security-relevant `backend/mtg_analyzer/parser/oracle/` pipeline).
      Three sub-tabs: **Statische Analyse** (mana curve by CMC bucket,
      card-type distribution, color pip counts vs. mana-source counts,
      land-archetype breakdown — basics/duals/fetches/shocks/MDFC-lands/…,
      and a "Command Zone" deckbuilding-template split: Lands/Ramp/Card
      Advantage/Targeted Disruption/Mass Disruption/Plan Cards);
      **Dynamische Analyse** (a hypergeometric opening-hand/by-turn land
      simulation, `expectedLandsOverTime`/`simulateManaCurve`, factoring in
      recognized accelerants — mana rocks/dorks/land-Auras/land-ramp
      spells vs. one-shot rituals/Treasure generators, classified
      separately since only the former are "recurring" for the sim); and
      **Bracket-Analyse**, a heuristic approximation of WotC's 5-tier
      "Commander Brackets" beta system (`suggestBracket`): flags Game
      Changers, Mass Land Denial, and Extra Turn spells (each via a
      hand-maintained name/pattern list, `isGameChanger`/
      `isMassLandDenial`/`isExtraTurn`) plus a Tutor count, and suggests a
      minimum bracket — explicitly labeled unofficial/approximate in the UI
      copy, since brackets also weigh un-derivable factors (combo speed,
      "stax" intent) the tool can't see from card text alone. Backed by
      `Deck.color_identity`/`.commanders` (`backend/Done_Backend.md`
      "Deck persistence") for the commander-vs-99 split. This is separate
      from, and doesn't block, the LLM-backed `POST /api/decks/{id}/analyze`
      analysis still in `docs/implementation-state/BACKLOG.md` "LLM Deck Analysis" — that
      endpoint would add synergy/archetype narrative on top of these
      numbers, not replace them.

## Multiplayer follow-ups (2026-08-04)

- [x] **PLR-5 · Periodic ping.** `lobbySocket.js` now sends `{type:
      'ping'}` every 30s while the socket is open (well under the default
      120s `MTG_MULTIPLAYER_IDLE_TIMEOUT`) — backend half (the `ping`
      handler now calling `lobby.touch`) in Done_Backend.md. The timer is
      started on `open`, cleared on `close`/the module's own `close()`, so
      it never outlives the socket it belongs to.
- [x] **VIS-5 · A move/priority feed.** `gameBoardView.js`'s `applyView`
      already computed "did `move_log` actually grow since the last view"
      to invalidate an in-progress block/targeting draft (PLR-6) — the new
      feed reuses that exact same delta to slice the newly-added `move_log`
      entries, zip them against the new `move_actors` (Done_Backend.md),
      and — for any actor that isn't `view.perspective` (so a solo mode,
      with no perspective at all, never populates it, and your own moves
      never echo back at you) — queue a short-lived toast ("Bob hat X
      gespielt", `pushMoveFeed`/`describeMoveLabel`, the latter translating
      a handful of common raw labels — `play_land`/`cast_spell`/
      `pass_priority`/`declare_attackers`/… — into a German verb phrase,
      falling back to the raw label same as the existing "Verlauf" panel
      already shows it). Rendered as `.gf-move-feed`, fixed near the top
      of the board, each toast fading out via a pure-CSS `@keyframes`
      animation over 6s and evicted from the underlying array by a
      matching `setTimeout` (so a stale entry can't resurrect on the next
      unrelated re-render). Capped at 3 concurrent toasts. Verified live
      against a running goldfish board (solo — confirms the feed correctly
      stays silent with no `perspective`) with zero console errors; the
      two-seat interactive case is covered by the backend's `move_actors`
      tests plus this module's reuse of PLR-6's already-proven delta logic.
- [x] **VIS-6 · Preload every seat's card art.** `preloadOwnDeck` (run at
      deck-pick time) only ever warmed *this* client's own deck, so an
      opponent's first play of a card popped in mid-game. New `multiplayerView.js`
      function `preloadAllDecksArt`, called once — when the table's first
      real view arrives (`applyGameView`'s existing `enteredBoardFor`
      "first view for this session" guard, by which point every seat's
      deck pick is locked in) — resolves every seat's `deck_id` against
      the already-fetched `savedDecks` (unscoped, this app has no
      accounts, so an opponent's saved deck is readable the exact same way
      `mySavedDeck()` reads your own) and preloads the union of every
      deck's card names through the same `preloadCardImages` goldfish's
      loading screen uses. Verified live: goldfish's own board (which
      shares `gameBoardView.js`/`cardImages.js` with this code path)
      rendered a full board with zero pop-in and zero console errors.
