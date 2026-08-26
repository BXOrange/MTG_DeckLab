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

### Einstellungen tab + cookie-persisted settings

- **What:** Player-name + server-address fields with "Speichern"/"Verbindung testen"; settings persist device-locally in cookies (`mtg_server_url`, `mtg_player_name`, 1-year expiry).
- **Files:** `connectionSettingsView.js`, `cookies.js`, `settings.js`

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

## Goldfish Board Core

### Goldfisch mode wired to the real engine

- **What:** The "Goldfisch" tab picks a saved deck (only a legal one enables Start), posts to `POST /api/game/goldfish`, and renders/drives the server's authoritative `GameState` via validated actions from `legal_actions`, plus Zurücknehmen (rewind) and Neu starten.
- **Files:** `goldfishView.js`
- **Why:** The old local rule-less "preview" board (`boardEngine.js`) was removed entirely once a real engine-backed board existed.

### Stack, phase/turn indicator, day/night badge

- **What:** LIFO stack display with a "Priorität abgeben" control resolving one item at a time; a topbar shows turn/phase/step plus a ☀️/🌙 day-night badge (RULE 731) that stays hidden until a designation is established.
- **Files:** `goldfishView.js`, `gameBoardView.js`

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

### Modal spell mode selection (bug fix)

- **What:** Every RULE 700.2 modal spell (choose one/N/N-or-more, Entwine) silently cast only its first listed mode — the board never round-tripped `mode`/`mode_description` through button labels, submitted actions, or `findTargetableAction`'s target-path matching, so clicking any mode button produced the same cast.
- **Files:** `gameBoardView.js`
- **Bug fixed:** Fixed by threading `mode`/`entwine` through every cast-button variant and widening action matching to disambiguate on `mode` (compared via `JSON.stringify` since a "choose N" mode is an array). Found via a user report initially misattributed to the unrelated triggered-ability "you may" choice path before being narrowed to modal spell casting specifically.

## Casting & Costs (frontend)

### X-spell and Kicker payment UI

- **What:** A hand/command-zone card with `{X}` in its cost gets a number input (defaults to max) instead of a plain cast button; a kickable spell separately gets a Kicker number input (defaults to 0, since it's an opt-in extra cost) — both compose when a spell is kickable and X-costed.
- **Files:** `goldfishView.js`, `gameBoardView.js`
- **Bug fixed:** `legal_actions` had surfaced kicker fields since an earlier batch, but neither the board nor `game_session.py`'s `cast_spell` handler ever read/forwarded a `kicked` field — so kicker payment couldn't have worked end-to-end regardless of UI. Fixed both sides together.

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

- **What:** In a shared game the toolbar shows "Passen" (not "advance step" — a step ends only when everyone passes) plus a badge for whose priority window it is; everything else is disabled outside your own window.
- **Files:** `gameBoardView.js`

### Auto-pass with countdown

- **What:** A visible countdown auto-passes priority at zero when this client holds it; any board interaction cancels the window. Default on, 3s, opponent-turns-only; adjustable in Einstellungen and on the board itself.
- **Files:** `gameBoardView.js`, `settings.js`

### Reconnect keeps your seat

- **What:** The lobby socket reclaims a seat by player name (Profil tab), so a reload/dropped connection lands back in the same game; a badge (⚡ getrennt) and drop-reason text (idle/replaced/timeout) surface connection state, which is lobby data reaching the board via a `seatStatus` hook.
- **Files:** `lobbySocket.js`, `gameBoardView.js`

### "Nächste Aktion" — skip empty priority windows

- **What:** A persisted toggle auto-passes through windows where `legal_actions` offers literally nothing but `pass_priority`, stopping at the first window that offers anything real — distinct from auto-pass, which is interruptible because there's something you could respond to.
- **Files:** `gameBoardView.js`
- **Bug fixed:** Could spam the server with redundant `pass_priority` calls fast enough to break the UI, because the multiplayer transport returns no fresh data from `act()` (it waits for the socket push) so the priority-window key could stay unchanged across renders while a pass was still in flight; fixed with a `skipAttemptedForKey` latch capping it to one attempt per window, verified via a headless JS-engine harness since there's no browser test runner.

### Board polish: sticky topbar, player counters, round vs. turn

- **What:** The turn/phase bar is sticky on scroll; poison/energy/Ring-level/Monarch/Initiative/emblems are now drawn (previously only life and mana pool were, despite already being in the payload); "Zug N" shows the round number (tooltip has the rules-correct per-player turn count).
- **Files:** `gameBoardView.js`

### Attachment targeting bug fix

- **What:** Equip/Fortify/Reconfigure were legal onto *any* creature/land, including an opponent's, though RULE 702.6a/702.67a/702.151a all say "you control" — a backend-only fix (targeting.py, rules_engine.py) at both offer-time and resolution-time.
- **Files:** `game/targeting.py`, `game/rules_engine.py`
- **Bug fixed:** Nothing had ever checked the "you control" qualifier on these three attachment abilities' legal targets.

### Vancouver mulligan + post-mulligan scry

- **What:** The scry after the whole table keeps arrives as an ordinary `pending_choice` on the board (not the mulligan screen, since setup is already over by then); mulligan screens now read the real shrinking hand size and share one `mulligan.js` text module instead of being duplicated per view.
- **Files:** `gameBoardView.js`, `mulligan.js`

### Move/priority feed (VIS-5)

- **What:** Short-lived toasts announce other seats' moves ("Bob hat X gespielt"), derived from the same move-log delta PLR-6's draft-invalidation logic already computes; silent for your own moves and in solo modes (no perspective).
- **Files:** `gameBoardView.js`

### Bot move pacing with speed control (VIS-7)

- **What:** A bot's whole turn arrives as one pushed view, so the move feed staggers each toast's reveal via `setTimeout` at a user-selectable pace (Sofort/Normal/Langsam) instead of showing a full bot turn's toasts simultaneously — a client-side replay of already-computed move-log data, not a server-push-per-ply change.
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

## Replay/Puzzle Mode

### 3-4 player Replay pods

- **What:** Two more start-screen buttons for 3/4-player puzzles; the play board needed no change (it already pods via the shared `gameBoardView.js`), and the from-scratch editor grid gained matching pod CSS.
- **Files:** `replayView.js`

## Deck Analysis (frontend)

### Static deck analysis (UC2)

- **What:** A fully local/static analysis (no backend call, no AI) over resolved card data: mana curve, type distribution, pip-vs-source counts, land-archetype breakdown, and a deckbuilding-template split (Lands/Ramp/Card Advantage/Disruption/Plan) — card classification is a display-only oracle-text heuristic, never affecting real game behavior.
- **Files:** `analyzeView.js`, `deckAnalysis.js`

### Dynamic simulation UI (ANA-4)

- **What:** The "Dynamische Analyse" sub-tab starts a background job (`POST /api/analysis/dynamic`) and polls for progress, then renders stat tiles and an SVG chart plotting simulated mana potential (mean ± stddev) against the static tab's already-computed curve, plus per-turn bar charts and an infinite-mana-guard warning count.
- **Files:** `dynamicAnalysisPanel.js`

### Bracket-Analyse heuristic

- **What:** A heuristic approximation of WotC's 5-tier Commander Brackets, flagging Game Changers/Mass Land Denial/Extra Turn spells via hand-maintained name/pattern lists plus a tutor count, explicitly labeled unofficial since real brackets also weigh un-derivable factors like combo speed.
- **Files:** `deckAnalysis.js`
