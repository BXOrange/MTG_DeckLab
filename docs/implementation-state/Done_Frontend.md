# Frontend — Done

**Catalogue** (organized by app area/feature, not by date): completed
frontend work and *why it was built that way*. Open work lives in
[BACKLOG.md](BACKLOG.md), under `VIS` and the other categories.

Entry headings are stable — a `Done_Frontend.md "<entry>"` reference from
the code lands here (Ctrl+F/grep the exact phrase). Entries written before
2026-07-27 cite a `ToDo_Frontend.md`/`ToDo_Backend.md` that no longer
exists; both were merged into `BACKLOG.md`, and those mentions have been
repointed there.

## Deck Import & Backend Integration

### Optimistic local parse + server-authoritative deck submit

- **What:** `parser.js` parses a pasted decklist client-side for instant feedback (a pending badge), then `submitDeck` posts to `POST /api/decks` and the server's response **replaces** `state.deck` — the server is always the source of truth.
- **Files:** `deckImportView.js`, `api.js`, `parser.js`

### Card data resolution & legality display

- **What:** Parsed card names resolve against the card database for mana cost/type/oracle text/P-T/images (`resolveCards`/`cardImageUrl`). Commander legality from `POST /api/decks` marks specific offending cards (❗ banned/color-identity) distinct from 🛑 "not found".
- **Files:** `api.js`, `cardImages.js`, `cardTile.js`

### Archidekt import tab

- **What:** A dedicated "Import Deck" sidebar tab (separate from the editor so a failed import doesn't dump the user into a half-populated editor) takes an Archidekt link/id via `GET /api/import/archidekt/{deckId}` and hands the result to the same `loadDeck` path a saved deck uses.
- **Files:** `importDeckView.js`, `api.js`
- **Why:** Moxfield fetch was tried and reverted twice (Cloudflare-blocked) — see Moxfield paste-import entry below for the workaround.

### Moxfield paste-import

- **What:** Since a live Moxfield fetch is Cloudflare-blocked, `parser.js`'s `parseMoxfieldExport` instead splits a pasted plain-text Moxfield export on its "SIDEBOARD:" marker. Commander detection is a real oracle-text/type-line check (`isCommanderCandidate`/`canPairAsCommanders`, mirroring the backend's Partner logic), not a text heuristic.
- **Files:** `parser.js`, `deckImportView.js`
- **Why:** An earlier textual heuristic (longest sorted suffix) was replaced same-session after a real export showed a second legendary creature right after the true commander that only a real legality check correctly excludes.

## Connection Settings & Profile

### Sidebar navigation + connection status

- **What:** Collapsible left sidebar nav (replacing old top-bar tabs) plus a header connection indicator polling `GET /api/health` every 5s, shared via pub/sub between the header and the Einstellungen status line.
- **Files:** `index.html`, `app.js`, `connectionStatus.js`

### Einstellungen tab and automatic server connection

- **What:** Backend requests use the page origin, with explicit development/deployment defaults in `settings.js`. The server-address field and cookie override are removed; stale `mtg_server_url` cookies are ignored. Connection status and "Verbindung testen" remain. Player preferences still persist device-locally in cookies.
- **Files:** `connectionSettingsView.js`, `cookies.js`, `settings.js`

### LLM settings and AI Bot status

- **What:** Settings configures a server-wide Claude/Anthropic or compatible endpoint, an automatically populated model dropdown (provider model-list API, manual fallback, reload and stale-response protection), enable flag, key, timeout and per-turn bot call budget, plus save/connection-test controls. Keys are never loaded into the browser; empty preserves and explicit clear removes the stored key. German/English copy explains that deck/game context goes to the provider. AI Bot is selectable through the existing bot catalogue. Solo shows thinking/fallback status and polls pending decisions without overwriting a newer action/restart view.
- **Files:** `connectionSettingsView.js`, `api.js`, `soloView.js`, `locales/{de,en}.js`; [LLM integration](../Reference/LLM_INTEGRATION.md).

### Local card-pool and combo-data updates

- **What:** Settings exposes separate controls to refresh the full Scryfall card pool and the Commander Spellbook SQLite snapshot. The latter's current source version/time and added/changed/removed variant counts are surfaced inline; the combo snapshot still remains lazy-loaded during analysis unless explicitly updated here.
- **Files:** `connectionSettingsView.js`, `api.js`

### Einstellungen ↔ Profil split (everything player-facing → Profil)

- **What:** The **Einstellungen** header tab provides backend connection tests,
  data updates and optional LLM configuration. Everything about the player moved to
  the **Profil** tab: player name (already there), multiplayer default
  settings + favorite decks (already there), and — newly relocated —
  the **Mehrspieler: Auto-Pass** / **Mehrspieler: Spielfeld** comfort
  toggles and the **Eigene Token-Bilder** / **Karten-Sleeves** upload
  sections. No behaviour change: same cookie keys (`settings.js`), same
  `player_assets.py` routes, same board hooks; only which of the two
  `render*(container)` views builds the markup and wires the listeners.
  `connectionSettingsView.js` dropped its `api.js` player-asset imports
  and its `view-shown` asset-refresh handler; `profileView.js` gained
  them and now also refreshes token art / sleeves on save and on
  `view-shown` alongside the favorites list.
- **Files:** `connectionSettingsView.js`, `profileView.js`
- **Why:** "Einstellungen" had grown into a catch-all; the mental model
  is now clean — *reaching the server* vs. *who you are / how you play*.

### VIS-1: error/loading states for network calls

- **What:** Closed the ticket, which read as a broad gap but turned out to
  already be mostly covered — every tab-level fetch already had a loading
  placeholder and a `server-status warning` "Server nicht erreichbar."
  message (`savedDecksView.js`/`cachedCardsView.js`/`connectionSettingsView.js`/
  `implementationStatusView.js`), on top of the header's own global
  connected/disconnected indicator (`connectionStatus.js`, above). What was
  actually missing: a real **spinner** (every "Lädt …" placeholder was bare
  italic text, `main.css`'s `.spinner` — a small CSS ring, `prefers-reduced-
  motion`-aware — is now prefixed onto each one); and, closer to a genuine
  bug than a missing nicety, three call sites where a failed fetch was
  silently indistinguishable from a legitimate empty result, so there was
  nothing *to* retry because the UI never admitted anything had failed.
  `implementationStatusView.js`'s coverage-by-set table set its `loaded`
  latch **before** knowing the fetch had succeeded, so a single failure
  disabled every future `view-shown` retry for the rest of the page's life
  — fixed to latch only on success, plus its own inline "Erneut versuchen"
  button rather than relying on "switch tabs away and back" as an
  undocumented workaround. `analyzeView.js`/`goldfishView.js`/
  `multiplayerView.js`'s saved-deck pickers all did `savedDecks = decks ||
  []` on `listSavedDecks()` returning `null` (network failure) — collapsing
  "couldn't check" into "checked, zero decks" and (via a `savedDecks ===
  null` re-fetch guard that a `[]` no longer satisfies) permanently
  suppressing every future retry too; a `decksLoadError` flag now keeps the
  two states apart, the picker shows "— Server nicht erreichbar —" instead
  of "— keine gespeicherten Decks —", and the retry guards check the flag
  alongside `=== null`. `replayView.js`'s "add card" search modal had the
  same shape (`cardPool = cards || []`, so a failed load read as "0 Treffer"
  on every future search instead of retrying) — kept `cardPool` `null` on
  failure instead.
- **Files:** `main.css` (`.spinner`), `implementationStatusView.js`,
  `analyzeView.js`, `goldfishView.js`, `multiplayerView.js`, `replayView.js`,
  `savedDecksView.js`, `cachedCardsView.js`, `connectionSettingsView.js`,
  `profileView.js`
- **Why:** The three-deck-picker bug is the same shape three times because
  all three copy the same "load once, guard re-fetch on `=== null`" idiom
  from each other rather than sharing it — worth knowing before "fixing"
  any one of them again in isolation.

## Saved Decks Management

### Saved-deck save split: update vs. new

- **What:** "Aktualisieren" (overwrite the loaded deck, sends its id) and "Als neues speichern" (always creates a fresh deck) replace a single ambiguous "Speichern" that silently overwrote the loaded deck.
- **Files:** `deckImportView.js`

### Saved-decks list with legality badges

- **What:** "Decks verwalten" lists saved decks (`GET /api/decks`), each row lazily fetching a legality badge (`GET /api/decks/{id}/validation`) — 🛑+reasons or ✅.
- **Files:** `savedDecksView.js`

### Cube flag ("Als Cube behandeln")

- **What:** A checkbox flags a saved deck as a card pool (`isCube`) rather than a real Commander deck, skipping legality checks; the list shows a 🧊 badge and a matching Deck/Cube filter instead of the legality fetch.
- **Files:** `deckImportView.js`, `savedDecksView.js`

### VIS-2 · Rename / duplicate-as-new

- **What:** "Umbenennen" and "Duplizieren" buttons per saved-deck row, both reusing the existing `POST /api/decks/save` (rename keeps the id; duplicate sends `id: null` and an appended "(Kopie)" name) — no new backend route needed.
- **Files:** `savedDecksView.js`

## Card Display & Art

### Card art, cache browser, and detail tiles

- **What:** Card art loads via the backend cache (`POST /api/cards/resolve` + `GET /api/cards/{id}/image`), never directly from Scryfall. "Karten-Cache" tab browses every cached card; a "Detailansicht" toggle switches deck-import lists to an image/mana-cost/oracle-text tile grid.
- **Files:** `cardImages.js`, `cachedCardsView.js`, `cardTile.js`

### Global card hover preview

- **What:** One floating hover panel driven by a single delegated `document` listener; any view opts in via `data-hover-card="<name>"`.
- **Files:** `cardHoverDetail.js`

### Faithful hybrid/Phyrexian mana-cost rendering

- **What:** `renderManaCost` token-parses the raw `mana_cost_string` to render hybrid/Phyrexian/X pips faithfully instead of collapsing them, mirroring the backend's `ManaSymbol` kinds; falls back to the old flattened approximation only for cards cached before that field existed.
- **Files:** `cardTile.js`

### Oracle-text mana symbol rendering

- **What:** `renderOracleText` applies the same mana-token renderer to a card's rules text (activation costs, "Add {G}"), not just its cost line, in both the cache tile and the hover tooltip.
- **Files:** `cardTile.js`, `cardHoverDetail.js`
- **Bug fixed:** The first cut double-wrapped the mana-token regex in an extra capture group for `.split()`, which inserts every capture group into the result — duplicating each token's bare content next to its emoji (caught live via Playwright against a real card cache, fixed with a dedicated single-group split regex).

### DFC front/back board rendering

- **What:** The battlefield board shows correct art for a transformed permanent's current face, with a "peek other face" preview button (client-only, doesn't touch game state) distinct from the real `transform` action.
- **Files:** `gameBoardView.js`, `cardImages.js`, `cardHoverDetail.js`
- **Bug fixed:** `resolveImageUrl` unconditionally returned the front-face art for an already-transformed permanent because the image cache was only ever keyed by the deck's front-face name; fixed by branching on face before trusting the cache hit, and by caching a DFC's entry under both front and back names.

### Vanilla-token art via a Scryfall-sourced token library

- **What:** A "1/1 white Soldier"-shaped token an effect synthesizes inline (no catalogue ability) now shows its real printed art by default instead of a text tile, for the overwhelming majority of tokens that don't already carry an ability (Treasure/Clue/… already had this via the small hand-curated `data/tokens.json`). `scripts/build_token_art_library.py` builds `backend/mtg_analyzer/data/token_art.json` from Scryfall's `default_cards` bulk dump (filtered to `set_type == "token"` real companion sheets, dropping ad/checklist/boxed-game filler mixed into the same layout), keyed by the exact **(name, power, toughness, colors)** combination — 639 entries across 422 distinct names as of the 2026-09 build. `TokenArtLibrary.find` (`services/token_database.py`) is consulted from `synthesize_token_card` (and so every one of its call sites — `CreateTokenEffect`, copy/Incubator/Endure/populate paths — for free) and from `services/replay.py`'s `_token_card` (the Replay/Puzzle board-editor add-token form); a miss leaves the pre-existing imageless behaviour untouched.
- **Why a (name, power, toughness, colors) key, not just name:** Magic reprints the same token name at different stat lines across sets — several "Shapeshifter" tokens exist as a 1/1, a 2/2 (blue), and a 3/2, and "Spirit" has 14 distinct stat/colour combinations — so a name-only lookup would show one variant's art on every other variant.
- **Frontend wiring:** `gameBoardView.js`'s `resolveImageUrl` now tries an id-keyed lookup *before* the existing by-name `imageCache` lookup, since two different token variants sharing a display name can't both win a by-name key; `goldfishView.js`/`soloView.js`/`multiplayerView.js`'s token-art preloaders (`preloadDeckTokens`/`preloadDecksTokens`) now seed `imageCache` by the token's own id first (unique per variant) and by name only as a same-name fallback + `cardImages.js` tooltip-cache key. Multiplayer additionally preloads every seat's producible tokens now, not just the client's own deck's (mirroring the existing VIS-6 all-seats card-art preload).
- **Known gap:** Replay/Puzzle's manually-typed add-token form resolves real art server-side (`_token_card`) but the frontend never preloads/receives it for a freeform (non-decklist-driven) token, so it still shows the text/generic fallback there — `GameObject.to_dict()` carries no image fields on the wire, and there's no "producible tokens" list to preload from in that mode. Goldfisch/Solo/Multiplayer (tokens created by real gameplay effects) are unaffected.
- **Files:** `backend/scripts/build_token_art_library.py`, `mtg_analyzer/services/token_database.py`, `mtg_analyzer/services/replay.py`; `frontend/src/js/gameBoardView.js`, `goldfishView.js`, `soloView.js`, `multiplayerView.js`.

## Goldfish Board Core

### VIS-11: Created planeswalker tokens on shared boards

- **What:** Jace tokens expose `is_planeswalker`, loyalty counters and both loyalty actions through the existing shared board path used by Goldfish, Replay, Solo and Multiplayer. The board already renders the loyalty badge and action buttons for tokens; no token-specific rendering branch is required. Engine-Status lists Empower Jace in both German and English.
- **Validation:** `tests/test_empower_jace.py` verifies shared session payloads and legal actions, actual loyalty activation, and Replay export/import. Art uses the existing token-library and uploaded-token fallback in `gameBoardView.js`.

### Goldfisch mode wired to the real engine

- **What:** The "Goldfisch" tab picks a saved deck (only a legal one enables Start), posts to `POST /api/game/goldfish`, and renders/drives the server's authoritative `GameState` via validated actions from `legal_actions`, plus Zurücknehmen (rewind) and Neu starten.
- **Files:** `goldfishView.js`
- **Why:** The old local rule-less "preview" board (`boardEngine.js`) was removed entirely once a real engine-backed board existed.

### Stack, phase/turn indicator, day/night badge

- **What:** LIFO stack display with a "Priorität abgeben" control resolving one item at a time; a topbar shows turn/phase/step plus a ☀️/🌙 day-night badge (RULE 731) that stays hidden until a designation is established.
- **Files:** `goldfishView.js`, `gameBoardView.js`
- **Bugfix (interactive board locked whenever a non-creature spell hit the stack):** `spellTypeLabel` (the stack-item badge) matched on `t` — the imported i18n *function* — instead of `tl`, the lower-cased type line, on every branch after "creature". For an instant/sorcery/artifact/enchantment/planeswalker spell that meant `t.includes(...)` → `TypeError: t.includes is not a function`, thrown out through `stackItemHtml` → `stackOverlayHtml` → `render()`. Because `withBusy` ran its first `render()` *before* its `try`, the throw escaped and left `busy` stuck true, disabling every priority/pass/cast control (`disabled = busy || …`) — reported as "as soon as spells go on the stack nothing reacts, all controls blocked". Fixed the `t`→`tl` typo (those 5 branches had *never* run, so their hard-coded German literals were dead code — now routed through new parity-matched `bd.stack.{instant,sorcery,planeswalker,artifact,enchantment,generic}Spell` keys) and moved `withBusy`'s first `render()` inside the `try` so a render exception can never wedge `busy` again. Creature spells and triggered/activated abilities were unaffected (earlier returns). Separate follow-up still open: reworking the stack/priority *interaction* itself (the modal-overlay "Zur Seite schieben" flow).

### Per-card action buttons from legal_actions

- **What:** Actions render directly under the affected card (land-play/cast buttons on hand cards, one tap button per mana option on lands, a per-creature attack button) rather than as aggregate global controls.
- **Files:** `goldfishView.js`, `gameBoardView.js`

### Art preload + London mulligan screen

- **What:** A loading screen preloads every deck card's art before the board first renders (fixing turn-by-turn art pop-in); a mulligan screen (London style) gates all other actions until the opening hand is kept, including the bottom-N-cards selection after N mulligans.
- **Files:** `goldfishView.js`

## Mana System (frontend)

### Restricted mana / any-combination color split / hand-zone mana abilities

- **What:** The mana pool renders RULE 605.3a restricted-mana lots with a 🔒 badge and a German tooltip; a 5-input WUBRG split builder appears for "any combination of colors" abilities (RULE 605.1a); hand-zone mana abilities ("Exile this card from your hand: Add …") get their own action button.
- **Files:** `gameBoardView.js`

### "May choose not to untap" toggle

- **What:** A sticky per-permanent toggle button for RULE 502.1's "may choose not to untap" permission.
- **Files:** `gameBoardView.js`
- **Why:** Verified against a synthetic single-ability test token in Replay mode, since every real printed card with this clause also pairs it with a second, still-unmodeled effect that keeps the whole card fail-closed at UNMODELED.

## Choice & Targeting UI

### Generic pending_choice modal coverage

- **What:** A themed modal panel answers any `pending_choice` kind server-side offers — library search, cascade/discover, replacement-order, shock-land pay-life, trigger target/"you may", trigger ordering, enter-as-copy, counter-unless-pays — via the shared `CHOICE_ICONS`/generic one-button-per-option mechanism.
- **Files:** `gameBoardView.js`

### Drag-and-drop replacement-order UI

- **What:** The one RULE 616.1e/f `replacement_order` choice gets a dedicated drag-and-drop reorder list — the app's only drag-and-drop UI — rather than the generic one-button-per-option modal; confirming replays the chosen order as ordinary sequential `choose` picks.
- **Files:** `gameBoardView.js`

### Generic spell/ability targeting modal

- **What:** `castTargetHtml`/`castTargetModalHtml` turn any `cast_spell`/`activate_ability` with `requires_target` into a modal that walks each target requirement in turn (multi-target support), offering "∅ Kein Ziel" when optional. One mechanism covers spell targeting, Aura-attach targeting, and Equip/Fortify/Reconfigure — no separate "equip control" was built.
- **Files:** `gameBoardView.js`

### Per-requirement target groups (MEC-10)

- **What:** Each expanded targeting round now remembers which requirement it belongs to, so a cast/activate with 2+ *different* targeting clauses ("pump target creature... it fights target creature you don't control") sends per-requirement `target_groups` instead of one flat list that could conflate them; the server derives the partition itself when unambiguous, but only the client can express a declined "up to one" slot.
- **Files:** `gameBoardView.js`
- **Why:** A flat list can't say *which* slot in a multi-round pick was left empty — that's the reason groups are sent client-side rather than re-derived.

## Card-Type & Structural UI

### Planeswalker loyalty display

- **What:** A ◆-badge shows current loyalty; `[+N]`/`[-N]`/`[0]` ability buttons get color-coded modifier classes.
- **Files:** `gameBoardView.js`

### Play/cast from library-top visualization

- **What:** The library zone renders the top card's face with whatever play/cast buttons `legal_actions` offers for it, whenever the new `top_library_visible` view flag is set (Oracle of Mul Daya/Glarb-shaped).
- **Files:** `gameBoardView.js`

### Per-card effect summary popover ("Info-Punkt")

- **What:** A Σ-badge on each battlefield card opens a native Popover-API panel listing every effect currently reshaping it (Auras, Equipment, anthems, counters, until-EOT buffs), each with source + duration chip + resulting P/T.
- **Files:** `gameBoardView.js`

### "Castable from exile" panel

- **What:** A dedicated panel lists every exile-zone card any of the three "you may cast this from exile" mechanisms (impulsive draw, Adventure, Prepared) currently allows, each with the same live cast button Hand/Battlefield use, plus a caption naming source and duration.
- **Files:** `gameBoardView.js`

### RULE 603.7 delayed-trigger panel

- **What:** A compact "planned" panel lists armed delayed triggers (Ephemerate's Rebound, Marchesa's counter-death return, Sneak Attack's cheat-in-then-sacrifice) with a thumbnail, description, and "⏳ Zu Beginn von …" timing line.
- **Files:** `gameBoardView.js`
- **Bug fixed:** Caught and fixed two pre-existing bugs while verifying this panel end-to-end: `RulesEngine.blink` left a phantom duplicate reference in the owner's exile list after returning a blinked object to the battlefield, and `legal_actions`'s exile loop never checked temp-play-permission-exiled cards (Light Up the Stage/Ragavan-shaped), so those could never actually be offered as castable despite the engine fully supporting it.

### Face-down permanents, dungeons, Planechase on the board

- **What:** Face-down permanents render the player's chosen card-back sleeve with a 🎭 badge naming why (Morph/Disguise/Manifest/Cloak) and one "Aufdecken" button per legal turn-up route; the player-counter strip gained dungeon/room, Vanguard avatar, and Archenemy scheme facts; a Planechase strip shows the face-up plane and planar-die action, rendering nothing outside that format.
- **Files:** `gameBoardView.js`
- **Bug fixed:** A hand card with morph/disguise offers *two* `cast_spell` actions (the ordinary front-face cast for its printed cost, and the RULE 702.37a face-down cast for `{3}`). `faceHint` had no `face === 'face_down'` case, so it fell through to the generic `— <card name>` suffix and the morph button rendered as `✨ Zaubern — Birchlore Rangers` — indistinguishable from a redundant second copy of the plain cast button, so clicking it dropped a nameless face-down 2/2 onto the battlefield instead of the real creature. `faceHint` now labels that offer `(cast face down — Morph {3}, a 2/2)` (new `bd.faceHint.faceDown` locale key, en+de). Engine was always correct — front-face `cast_spell` resolves the creature normally; this was purely the button label.

### Modal spell mode selection (bug fix)

- **What:** Every RULE 700.2 modal spell (choose one/N/N-or-more, Entwine) silently cast only its first listed mode — the board never round-tripped `mode`/`mode_description` through button labels, submitted actions, or `findTargetableAction`'s target-path matching, so clicking any mode button produced the same cast.
- **Files:** `gameBoardView.js`
- **Bug fixed:** Fixed by threading `mode`/`entwine` through every cast-button variant and widening action matching to disambiguate on `mode` (compared via `JSON.stringify` since a "choose N" mode is an array). Found via a user report initially misattributed to the unrelated triggered-ability "you may" choice path before being narrowed to modal spell casting specifically.

## Casting & Costs (frontend)

### Gift recipient cast offers (RULE 702.174)

- **What:** Each server-provided Gift cast offer is rendered as a distinct button naming the
  recipient. `gift_opponent_id` is preserved through plain, `{X}`/Kicker, discard-cost and
  multi-step target-selection flows, and is part of legal-action matching so one opponent's
  target requirements cannot be confused with another cast offer.
- **Files:** `gameBoardView.js`, `locales/{de,en}.js`

### X-spell and Kicker payment UI

- **What:** A hand/command-zone card with `{X}` in its cost gets a number input (defaults to max) instead of a plain cast button; a kickable spell separately gets a Kicker number input (defaults to 0, since it's an opt-in extra cost) — both compose when a spell is kickable and X-costed.
- **Files:** `goldfishView.js`, `gameBoardView.js`
- **Bug fixed:** `legal_actions` had surfaced kicker fields since an earlier batch, but neither the board nor `game_session.py`'s `cast_spell` handler ever read/forwarded a `kicked` field — so kicker payment couldn't have worked end-to-end regardless of UI. Fixed both sides together.

### Additional-cost discard picker (RULE 601.2b / 602.1)

- **What:** A spell whose additional cast cost is "discard N cards" (Thrill of Possibility, Cathartic Reunion, Tormenting Voice, Wild Guess, Big Score, …) now opens the same one-pick-at-a-time modal the tap/sacrifice cost choices use, so the player chooses *which* cards pay it, and the picks ride the cast action as `discard_choices`. The modal heading/glyph (🗑️) mark it as a cost choice, not a RULE 115 target.
- **Files:** `gameBoardView.js` (`data-discard-choice-start` branch + handler, `isDiscardChoice` in `finishCastIfReady`/`castTargetModalHtml`/draft-restore), `game/engine/legal_actions_mixin.py` (`_cast_action` surfaces `discard_cost` = `{count, options}`), `services/game_session.py` (`_dispatch_cast_spell` now resolves and forwards `sacrifice_choice`/`discard_choices`).
- **Bug fixed:** the engine (`_resolve_discard_cost`, ENG-3) had accepted `discard_choices` on `cast_spell` since the cost-payment-choices batch, but `_dispatch_cast_spell` silently dropped the field (same shape as the earlier `kicked` bug) and the board never prompted — so a rummage spell always auto-discarded the front of the hand with no way to choose. Fixed all three layers together; covered by `test_game_session.py::test_cast_spell_forwards_discard_choices_for_an_additional_cost`.

## Multiplayer Lobby

### Setup/Board split + lobby presence

- **What:** "Setup" (lobby: players' presence, tables, seats, ready toggles, host controls) and "Board" (the shared game, disabled until seated) are two tabs under one persistent controller, matching the Goldfisch/Replay pattern.
- **Files:** `multiplayerView.js`

### Bot seats (UC5)

- **What:** The host fills a free seat with a bot from a server-driven kind picker (`GET /api/multiplayer/bots`); a bot seat renders like any other (🤖 badge, dashed border) with host-only deck-pick and remove controls before the game starts.
- **Files:** `multiplayerView.js`

### Per-seat take-backs

- **What:** A host-set "Take-backs je Spieler" field in Setup and, in-game, a "↩️ Zug zurücknehmen (N)" button showing the caller's own remaining count.
- **Files:** `multiplayerView.js`, `gameBoardView.js`
- **Why:** Its tooltip explains that undoing your own last move also undoes anything an opponent did since — there is only one shared timeline.

### Pod-sized tables (2-4 seats) + 2x2 layout

- **What:** A seat-count selector in Setup; on the board, 3-4 seat games tile in a clockwise 2x2 grid (`.gf-pod-grid`) with fold buttons per opponent section, boards ordered by real turn order (a rotation, not a sort) so your own seat is always last/nearest.
- **Files:** `multiplayerView.js`, `gameBoardView.js`
- **Why:** Seats use explicit `grid-area` per position rather than row-major auto-placement, because row-major fill would put the third seat bottom-left and run the turn ring backwards across the bottom row.

### Banner colors per seat

- **What:** A seat picks a subset of WUBRG (or none, for grey) to paint its board title bar; the picker is five toggles rather than 32 named options, since a banner color is literally a set.
- **Files:** `bannerColors.js`, `gameBoardView.js`, `multiplayerView.js`
- **Why:** All 32 combinations render through one CSS rule fed two `linear-gradient` custom properties per seat, rather than 32 enumerated classes.

## Multiplayer Board & Shared-Game UX

### Redacted opponent hands + observer mode

- **What:** An opponent's hand renders as a count (or card backs, togglable) since the server never sends its contents (RULE 400.2); "👁️ Zuschauen" opens a no-controls, no-hands observer board.
- **Files:** `gameBoardView.js`

### Blocker declaration UI (RULE 509.1a)

- **What:** One row per potential blocker with a dropdown of legal attackers; picks accumulate in a local draft and submit as one whole-block action (needed for menace validation across the complete assignment). Shared with Replay's play mode. "Blockt nicht" is a submittable empty-assignments answer, not just an absent one.
- **Files:** `gameBoardView.js`

### Per-creature attacker selection (VIS-3)

- **What:** Each attack-eligible card has its own attack button (single click with 0-1 legal defenders, a per-defender menu with 2+ — 3+ player pods, battles, planeswalkers) rather than one aggregate "swing with everybody" control.
- **Files:** `gameBoardView.js`

### Interactive priority UI (RULE 117)

- **What:** In a shared game the primary control is "Passen" (not "advance step" — a step ends only when everyone passes); who is active / who holds priority is shown only on each player's own banner now, not as a separate toolbar badge.
- **Files:** `gameBoardView.js`

### Left rail: turn/phase, inline stack, per-priority countdown

- **What:** The board's old sticky topbar + overlaid stack popup + top toolbar were replaced by one narrow **left rail** (`.gf-rail`) shared by every mode (Goldfisch/Solo/Replay/Multiplayer): turn+phase at the top, the **stack inline** below it as a vertical column of the same mini card views the old overlay used (`stackItemHtml` — the spell's card, or an ability's source permanent with its text overlaid, plus a Zauber/ausgelöste/aktivierte-Fähigkeit badge and LIFO position), never covering the board — resolved entries linger ~2s greyed-out as `resolvedGhosts` (also rendered via `stackItemHtml` with `{ ghost: true }`) so it stays briefly visible what went on the stack, solo modes included. A bot/opponent cast is drained off the stack server-side before the client ever sees it there (`run_bots`/`_advance_solo_bots` answer to completion before returning), so `applyView` also synthesises a ghost from each new `cast_spell`/`activate_ability` `move_log` entry by another actor (`syntheticStackItemFromMoveLabel`), staggered on `botSpeedMs` (VIS-7) and de-duped against the live stack + existing ghosts. Then only the table/layout controls at the bottom (Zonen-Seite, Bot-Tempo, `extraControls` like Aufgeben/Export). **"Passen" is not in the rail** — it sits on the priority holder's own board banner (`priorityBits`), next to the cards. On game start `gameBoardView.start()` dispatches `mtg-game-started` and `app.js` folds the app's side menu away for full board width; `mtg-game-ended` brings it back. Below 1200px the rail becomes a horizontal strip.
- **Files:** `gameBoardView.js`, `app.js`, `main.css`

### Per-priority countdown (server-set, response windows only)

- **What:** A **response** clock — it always runs while this client holds priority **on another player's turn**, which is the window a phase hands round to the other players once the active player is done. On your **own** turn (`autoPassArmed`/`railTimerHtml` both gate on `reactTimerSuppressedHere()`) it's suppressed during your main phases and combat — you're the one developing the board/attacking there (RULE 117), and a half-finished turn mustn't tick away under you — but it still runs whenever there's something on the stack to respond to, or during the passive **upkeep**, **draw** and **end** steps (`OWN_TURN_TIMER_STEPS`), where you're mostly just watching for a reason to act. A genuinely absent active player is the server idle-timeout's job (`MTG_MULTIPLAYER_IDLE_TIMEOUT`), not this. When it does run, the rail shows a shrinking bar and auto-passes at zero; any board interaction (a click anywhere in `.gf-stage`) — or the rail's "⏸ Unterbrechen" button — cancels it for that window. No opt-in checkbox (the Profil auto-pass section + its `getAutoPassEnabled`/`getAutoPassScope`/`getAutoSkipEmpty` cookies are gone; `getAutoPassSeconds` became `getPassTimerSeconds`, default 20, 0–600). The length is a **server** value, `view()["priority"]["timer_seconds"]` ← `config.MULTIPLAYER_SPELL_TIMER_SECONDS` (`MTG_MULTIPLAYER_SPELL_TIMER`, default 20s, 0 = off): **Multiplayer** host-overrides it per table in Setup (`LobbyGame.spell_timer_seconds`); **Solo vs. Bots** picks it in the start panel (`SoloStartRequest.spell_timer_seconds` → `create_multiplayer`), seeded from/saved to the `getPassTimerSeconds` cookie. "Skip empty windows" is always-on and runs *before* the timer check, so a window with nothing to respond to at all (an empty upkeep/draw/end with no instant/ability available) is passed through instantly rather than shown a bar, even in the three steps above.
- **Files:** `gameBoardView.js`, `multiplayerView.js`, `soloView.js`, `settings.js`, `profileView.js`, backend `config.py`, `services/lobby.py`, `api/schemas.py`, `api/multiplayer.py`, `api/solo.py`, `services/game_session.py`

### Take-backs on the player's own banner

- **What:** When the table configured a take-back budget, the "↩ Zurücknehmen (n)" button now sits on this client's own board banner (via a `transport.takeBack` hook) instead of being one of the toolbar controls.
- **Files:** `gameBoardView.js`, `multiplayerView.js`

### Reconnect keeps your seat

- **What:** The lobby socket reclaims a seat by player name (Profil tab), so a reload/dropped connection lands back in the same game; a badge (⚡ getrennt) and drop-reason text (idle/replaced/timeout) surface connection state, which is lobby data reaching the board via a `seatStatus` hook.
- **Files:** `lobbySocket.js`, `gameBoardView.js`

### Skip empty priority windows (automatic)

- **What:** Windows where `legal_actions` offers literally nothing but `pass_priority` are passed straight through, **unconditionally** (`skipEmptyArmed()`/`syncAutoPass`), chaining through consecutive empty windows one render at a time and stopping at the first window that offers anything real. There is **no manual "⏭ Nächste Aktion" button** on the shared board — it was removed once the skip went always-on (`skipToActionButtonHtml`, the `data-skip-empty` handler, the dead `skipBurstArmed` flag, the `bd.ctrl.nextAction`/`bd.ctrl.skipEmptyTitle2` keys and `.gf-banner-skip` CSS are all gone): it only ever did what the automatic skip already does, and never passed a window that had a real action. (Goldfisch's `#gf-next-decision` is unrelated — a server-side fast-forward over whole *steps*, solo only.)
- **Files:** `gameBoardView.js`, `styles/main.css`, `locales/{en,de}.js`
- **Bug fixed:** Could spam the server with redundant `pass_priority` calls fast enough to break the UI, because the multiplayer transport returns no fresh data from `act()` (it waits for the socket push) so the priority-window key could stay unchanged across renders while a pass was still in flight; fixed with a `skipAttemptedForKey` latch capping it to one attempt per window, verified via a headless JS-engine harness since there's no browser test runner.

### "End the turn" (manual speed-up, deliberate)

- **What:** A button on the priority holder's own banner, next to "Passen" — click it and every priority window this client holds for the rest of *this* turn auto-passes via `pass_priority`, **regardless of what `legal_actions` offers** (`endTurnActiveHere`). Unlike the automatic skip-empty above, it deliberately overrides "there's something you could do here" — the point is a player who's decided they have nothing left they want to do this turn and would rather fast-forward than click "Passen" through every remaining window (own main phases/combat included: it also force-passes those). Armed for exactly the internal turn it was clicked on (`endTurnAtTurnNumber` vs. `GameState.internal_turn.number`, RULE 500.1), so it never bleeds into the next turn; self-disarms once that turn ends, and on any genuine board interaction (`cancelAutoPassForThisWindow`, the same "you're clearly still deciding" signal the countdown listens to — checked unconditionally there, since a forced pass never starts `autoPassTimer` for the early-return guard to catch). It never answers a `pending_choice` or a turn-based action (declare attackers/blockers) — neither goes through `pass_priority`, so it can't silently skip one. Button text is the literal English "End the turn" in both locales (`bd.ctrl.endTurn`/`bd.ctrl.endTurnTitle`), by request.
- **Files:** `gameBoardView.js`, `styles/main.css`, `locales/{en,de}.js`

### Board polish: player counters, round vs. turn

- **What:** poison/energy/Ring-level/Monarch/Initiative/emblems are now drawn (previously only life and mana pool were, despite already being in the payload); "Zug N" shows the round number (tooltip has the rules-correct per-player turn count). The turn/phase readout moved from a sticky topbar into the left rail (see "Left rail" above), which also retired the topbar's turn-order strip.
- **Files:** `gameBoardView.js`

### Attachment targeting bug fix

- **What:** Equip/Fortify/Reconfigure were legal onto *any* creature/land, including an opponent's, though RULE 702.6a/702.67a/702.151a all say "you control" — a backend-only fix (targeting.py, rules_engine.py) at both offer-time and resolution-time.
- **Files:** `game/targeting.py`, `game/rules_engine.py`
- **Bug fixed:** Nothing had ever checked the "you control" qualifier on these three attachment abilities' legal targets.

### Vancouver mulligan + post-mulligan scry

- **What:** The scry after the whole table keeps arrives as an ordinary `pending_choice` on the board (not the mulligan screen, since setup is already over by then); mulligan screens now read the real shrinking hand size and share one `mulligan.js` text module instead of being duplicated per view.
- **Files:** `gameBoardView.js`, `mulligan.js`

### Move/priority feed (VIS-5) — removed

- **What:** Originally short-lived toasts (fixed top-right) announcing other seats' moves ("Bob hat X gespielt"), plus a "Verlauf" move-log panel under the board. Both were removed on request — the toast feed (`gf-move-feed`/`pushMoveFeed`/`describeMoveLabel`) and the panel (`moveLogHtml`/`gf-movelog`) are gone, along with their `bd.move.*`/`bd.moveLog.heading` locale keys. The move-log *delta* is still computed for PLR-6 draft-invalidation and for the VIS-7 rail-stack ghosts below.
- **Files:** `gameBoardView.js`, `styles/main.css`, `locales/{en,de}.js`

### Bot move pacing with speed control (VIS-7)

- **What:** A bot's whole turn arrives as one pushed view, so `applyView` synthesises a rail-stack ghost from each new `cast_spell`/`activate_ability` `move_log` entry by another actor and staggers those ghost reveals via `setTimeout` at a user-selectable pace (Sofort/Normal/Langsam) instead of flashing a full bot turn's casts in at once — a client-side replay of already-computed move-log data, not a server-push-per-ply change. (Originally also paced the VIS-5 toast feed, now removed.)
- **Files:** `gameBoardView.js`, `settings.js`

### A finished game closes deliberately

- **What:** The end-of-game digest no longer irreversibly hijacks the board — "Spielfeld ansehen"/"Auswertung" toggle back and forth, and "Spiel schließen" is a separate explicit action that removes the dead table from every remaining viewer's lobby list.
- **Files:** `multiplayerView.js`

### Periodic lobby ping (PLR-5)

- **What:** The lobby socket sends a ping every 30s (well under the idle timeout) so a connected-but-quiet client isn't dropped as idle.
- **Files:** `lobbySocket.js`

### Preload every seat's card art (VIS-6)

- **What:** Once a table's first real view arrives, every seat's deck (not just this client's own) is preloaded so an opponent's first play never pops in unloaded art.
- **Files:** `multiplayerView.js`

### In-progress selections survive a reconnect (PLR-6)

- **What:** Block/cast-targeting drafts are mirrored to the backend as they're built and best-effort rehydrated on reconnect, instead of being wiped on every fresh view (previously any unrelated seat's socket reconnect would blow away another player's in-progress pick).
- **Files:** `gameBoardView.js`

### "Save as Replay" from Multiplayer (PLR-10)

- **What:** Ports goldfish's existing "Als Replay speichern" button (already mode-agnostic server-side) onto the Multiplayer board's seat controls, for both in-progress and finished games.
- **Files:** `multiplayerView.js`

## Solo vs. Bots

### "Solo gegen Bots" mode (PLR-14)

- **What:** A new Singleplayer tab (`data-tab="solo"`, between Goldfisch and Puzzle/Replay) to play a saved deck against 1–3 bots on the **real Multiplayer rules engine** — genuine opponent turns, the stack, RULE 117 priority played out, hidden opponent hands — but with **no lobby, no WebSocket, no other humans**. `soloView.js` is a persistent controller shaped like `goldfishView.js`'s (`mount`/`onShown`, phases `pick → loading → mulligan → playing → summary`); the interactive board is the shared `gameBoardView.js`, driven by a Multiplayer-style transport (`allowRewind:false`, `allowFastForward:false` — interactive priority means "Passen", not "Zug weiter"; the board's own client-side auto-pass carries the bots' priority windows). The POST reply from `/api/solo/{id}/action` already carries the position *after* the bots have answered (`_advance_solo_bots` server-side), so — unlike Multiplayer, which waits for a socket push — the transport hands that view straight back to the board.
- **Start panel:** the human's deck `<select>` + legality gate (reused from goldfish), a format `<select>`, an **opponents** section (1–3 rows: bot-kind `<select>` from `GET /api/multiplayer/bots`, deck `<select>` defaulting to "wie dein Deck" = mirror match), and a "Wer beginnt? Du / Zufällig" (`startingPlayer`, maps to seat order server-side). Card art for every seat's deck + the human deck's producible tokens is preloaded on the loading screen.
- **Backend:** `api/solo.py` — `POST /api/solo/start` / `{id}/action` / `{id}/concede` / `{id}/restart`, `GET`/`DELETE /api/solo/{id}`. Reuses `sessions.create_multiplayer` (mode `MULTIPLAYER` → interactive priority + redacted views), `bots.create_bot`/`run_bots`, and `api/game.resolve_seat_deck` (extracted from `api/multiplayer.py` so both share it). The bot roster lives on the session (`session._solo_bots`, the same stash idiom `create_replay` uses); `_advance_solo_bots` is a bounded `run_bots` loop that stops the moment the human has a *real* decision (a castable card, a block, a pending choice, priority on its own turn) or the game ends — no background task.
- **Auto-passing the human through a bot's turn (backend, PLR-14 follow-up):** `_advance_solo_bots` also submits `pass_priority` *for* the human seat itself whenever `_human_only_passes(session)` — the human holds priority on an *opponent's* turn with `pass_priority` as its single legal action. Without it, every step of a bot's turn (upkeep, draw, each combat step, …) handed an empty priority window straight back to the client, and the game only crept forward one 3-second board-side auto-pass countdown at a time — which reads as the table hanging for the whole bot turn (the reported "hangs in the draw step"). This is the server-side twin of the board's own `autoSkipEmpty` (`frontend/src/js/settings.js`), always on for solo because a bot opponent gives the human nothing to respond to between turns; the human's *own* turn is still stepped by the client. `SOLO_BOT_ADVANCE_ROUNDS` was raised 20 → 120 to cover several bots' turns back to back in one response.
- **Rail exit control:** the rail shows **"🏳️ Aufgeben"** (concede → review) *only while the game is live* and **"Beenden"** (`quit` → review / deck picker) *only once it's over* — never both at once (they were doing the same thing side by side during play). `restart`/`export` stay in both states.
- **Shared with Goldfisch & Multiplayer (`gameSetup.js`, new):** `escapeHtml`/`escapeAttr`, the favorites-first deck `<option>` builder (`deckSelectOptionsHtml` — loading/error/empty states), `formatSelectOptionsHtml`, the mulligan hand tile (`mulliganTileHtml`), and the win/loss banner (`resultBannerHtml`). These were copy-pasted in both `goldfishView.js` and `multiplayerView.js`; `soloView.js` is the third caller, so they moved here once and both existing views were retrofitted to import them (behaviour-preserving — the markup output is unchanged).
- **"⚠️" deck-picker marker (`loadUnmodeledDeckIds` in `gameSetup.js`):** every deck `<select>` in all three pickers (Goldfisch, Solo — own deck + opponent rows, Multiplayer — own seat + bot seats) prefixes a deck's `<option>` with "⚠️" when it holds cards the rules engine doesn't model yet (a goldfishing-readiness hint, not a legality gate — same signal the saved-decks list already shows as "⚠️ N Karte(n) nicht modelliert"). `deckSelectOptionsHtml` gained an `unmodeledDeckIds` param; each view fills its own `Set` after the deck list loads via `loadUnmodeledDeckIds(savedDecks)` — one `GET /api/decks/{id}/coverage` per deck, all in parallel, failures tolerated (an unchecked deck is simply left unmarked). Non-blocking: the picker renders immediately and repaints once the checks land.
- **Files:** `soloView.js` (new), `gameSetup.js` (new), `api.js` (`startSolo`/`sendSoloAction`/`concedeSolo`/`restartSolo`/`endSolo`/`getSoloView`; `getDeckCoverage` already existed), `app.js` + `index.html` (tab wiring), `goldfishView.js` / `multiplayerView.js` (retrofit to `gameSetup.js` + the `unmodeledDeckIds` wiring). Backend: `api/solo.py` (new), `api/game.py` (`resolve_seat_deck` public), `api/multiplayer.py` (import it), `api/app.py` (router), `api/schemas.py` (`SoloStartRequest`/`SoloOpponent`).
- **Tests:** `backend/tests/test_api_solo.py` — start (setup view, bot seated, RULE 400.2 redaction of the bot's hand), rejects (unknown deck → 422, 0/4 opponents → 400, unknown bot kind → 400), keep-hand completes setup with the human on the play, passing through the turn lets the GoldfishBot play a land, `_advance_solo_bots` terminates on a bot-only stretch, the human is never handed an empty pass-only priority window on a bot's turn (the auto-pass follow-up), concede → game over in the bots' favour, restart → back to setup, GET/DELETE lifecycle. Frontend verified with Playwright end to end (pick → mulligan → board → 59× "Passen" → the bot has 3 lands on the board by turn 3, zero console errors).

## Replay/Puzzle Mode

### 3-4 player Replay pods

- **What:** Two more start-screen buttons for 3/4-player puzzles; the play board needed no change (it already pods via the shared `gameBoardView.js`), and the from-scratch editor grid gained matching pod CSS.
- **Files:** `replayView.js`

## Deck Analysis (frontend)

### Static deck analysis (UC2)

- **What:** Static browser-side deck metrics plus a lazy backend match against Commander Spellbook's locally stored snapshot; matched fixed-card variants display their uses, outputs, mana-value total and curve-estimated earliest turn. Unresolved card lists skip combo matching, and template requirements remain explicitly unverified.
- **Files:** `analyzeView.js`, `deckAnalysis.js`

### Dynamic simulation UI (ANA-4)

- **What:** The "Dynamische Analyse" sub-tab starts a background job (`POST /api/analysis/dynamic`) and polls for progress, then renders stat tiles and an SVG chart plotting simulated mana potential (mean ± stddev) against the static tab's already-computed curve, plus per-turn bar charts and an infinite-mana-guard warning count.
- **Files:** `dynamicAnalysisPanel.js`

### Bracket-Analyse heuristic

- **What:** The unofficial heuristic now also uses Commander Spellbook matches, narrowly requiring a two-card variant with an explicit infinite output, no unverified template requirements, and known card mana values. Combined card mana value is compared with the deck's max expected-mana curve: payable by turn 6 suggests Bracket 4; later suggests Bracket 3. This project-defined threshold is labeled as a heuristic, not an official WotC numeric rule or a game simulation.
- **Files:** `deckAnalysis.js`
