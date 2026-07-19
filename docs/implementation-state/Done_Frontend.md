# Frontend — Done

Completed frontend work, split out of
[`../../frontend/ToDo_Frontend.md`](../../frontend/ToDo_Frontend.md) (which
now holds only open items). Section headers mirror that file.

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
      `backend/ToDo_Backend.md`/`Done_Backend.md` "Card-type & structural
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

## Multiplayer

- [~] A dedicated **"Multiplayer"** sidebar tab (`multiplayerView.js`):
      calls `POST /api/game/multiplayer` and shows the backend's 501
      "not yet" message. Stubbed on purpose — the interactive priority
      loop isn't built server-side yet.

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
      analysis still in `backend/ToDo_Backend.md` "LLM Deck Analysis" — that
      endpoint would add synergy/archetype narrative on top of these
      numbers, not replace them.
