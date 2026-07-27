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
