# DeckLab: Game UI & Card Interaction Model

This document describes how the interactive game board actually works today:
plain vanilla JavaScript rendering a server-authoritative game state, with
every legal action computed by the rules engine and simply displayed by the
client. It replaced an earlier version of this file that illustrated the same
principles with invented React/JSX components (`CardInHand.jsx`,
`TargetingPanel`, `useState`) — this project has no React, no JSX, and no
build step at all; see [`03_ARCHITECTURE_AND_BUILDPLAN.md`](03_ARCHITECTURE_AND_BUILDPLAN.md)
for the system-wide picture and the API/session doc (`04_SERVER_CLIENT_ARCHITECTURE.md`)
for how a session's HTTP/WebSocket surface is shaped. What follows only
covers the board itself: `frontend/src/js/gameBoardView.js` and the small
set of modules around it.

---

# PART 1: CORE PRINCIPLE — CARDS ARE INTERACTIVE, ACTIONS ARE SERVER-DECIDED

A card in hand or on the battlefield is never rendered as inert text or a
bare image with a generic "play" button guessing what's legal. Every frame,
the client asks the server "what can this player actually do right now?"
(`GameEngine.legal_actions` / `GameSession.view()`, `backend/mtg_analyzer/
game/engine/legal_actions_mixin.py`, `services/game_session.py`) and renders
*exactly* that answer — nothing is computed or guessed client-side. If a
creature has no legal action this turn, it renders with no action buttons at
all; if a spell needs a target it can't currently find, the server marks the
offer `locked` with a human-readable reason and the client shows a disabled,
padlocked button rather than letting the click reach the server just to
bounce.

This is still the right framing the old doc had — cards are interactive
objects, not static display — it just isn't implemented as a click-to-open
component tree. In the real code, `frontend/src/js/gameBoardView.js`'s
`objCard()` renders one card tile per `GameObject`, and `cardActionButtons()`
turns that object's slice of `legal_actions` directly into one button per
action, appended right underneath the tile — always visible when legal,
never behind a click-to-reveal menu. A card with two legal actions (say,
`play_land` and an activated ability) simply shows two buttons.

---

# PART 2: HOW LEGAL ACTIONS REACH THE CLIENT

The engine's own timing rules (RULE 601/602/117, priority, stack) are the
rules engine's job, not this document's — see `CLAUDE.md`'s "Implementation
state" section and `04_SERVER_CLIENT_ARCHITECTURE.md` for that. What matters
for the UI is the shape of what crosses the wire:

- `GameEngine.legal_actions(player)` walks hand/command/exile/battlefield
  and returns a flat list of plain dicts, each `{"type": "cast_spell" | ...,
  "instance_id": ..., ...}` plus whatever fields that action needs (a
  `cast_spell` entry carries `requires_target`/`targets`/`has_x`/`max_x`/
  `cost_label`/`locked`+`lock_reason`; `declare_blockers` carries
  `legal_attackers`; `tap_for_mana` carries its color/amount `options`; …).
  There is no separate client-side legality layer — a `_castable_now_or_
  via_potential` check server-side decides whether an offer appears at all.
- `GameSession.view(perspective=...)` (`services/game_session.py`) wraps the
  serialized `GameState` with that player's own `legal_actions`, priority
  info (`view.priority.player_id`/`interactive`/`timer_seconds`), the
  `pending_choice` (if any), and — in multiplayer — redacts every zone RULE
  400.2 says this perspective shouldn't see. Solo modes (goldfish, Replay,
  Solo gegen Bots with no live opponent) call `view(None)`, which keeps the
  full unredacted state since there's no one to hide it from.

A trimmed, real shape (fields drawn from `_cast_action`/`legal_actions`,
not invented):

```json
{
  "type": "cast_spell",
  "instance_id": 42,
  "name": "Lightning Bolt",
  "requires_target": true,
  "targets": [
    {
      "label": "target creature or player",
      "options": [
        { "instance_id": 17, "name": "Grizzly Bears" },
        { "player_id": "p2", "name": "Opponent" }
      ]
    }
  ],
  "cost_label": "{R}",
  "locked": false
}
```

The client never re-derives this — `gameBoardView.js` indexes `legal_actions`
by `instance_id` once per render (`byInstance`, built in `render()`) and
looks up a card's own slice when drawing its tile.

---

# PART 3: RENDERING THE BOARD

`gameBoardView.js`'s `createGameBoardView()` is the real analog of the old
doc's React components — one controller object holding the session's live
`view`, wired into a DOM node via `mount(el)`. There is no virtual DOM: every
state change (a fresh view from the server, a UI-only toggle like
"three battlefield rows") calls `render()`, which rebuilds the whole board's
`innerHTML` from template-literal strings and then calls `wire()` to attach
event listeners to whatever now exists in the DOM. This is the same pattern
every view in the app uses (`CLAUDE.md`: "Plain `render*(container)`
functions... set `innerHTML` and wire listeners"), just larger, because the
board is the single most stateful screen in the app.

Key rendering functions inside `gameBoardView.js`:

- `objCard(obj, imageCache, cardActions)` — one card/permanent tile: image
  (falling back to name text), tapped/summoning-sick/targeted/attacking
  state as CSS classes, badges for loyalty/lore/defense/counters/keywords,
  and — via `cardActionButtons(cardActions)` — its own legal-action buttons
  directly beneath it.
- `handHtml(player, byInstance, pending, isOwn)` / `battlefieldHtml(...)` —
  the zone-level layout; battlefield permanents are grouped into rows by
  type (creatures / artifacts+enchantments / lands), a client-only layout
  preference persisted via a cookie (`gf_board_rows`), not a rules concept.
  An opponent's hand renders as face-down slots (`faceDownCardHtml()`)
  unless the "Gegnerhand zeigen" debug toggle is on, or the server actually
  sent revealed cards (RULE 400.2 stays server-enforced regardless of the
  toggle).
- `playerBoardHtml(...)` / `boardsHtml(...)` — one full board per player
  (mana/life header, command/library/graveyard/exile column, battlefield +
  hand), concatenated in turn order with this client's own seat drawn last
  (nearest the "camera"); three or more live boards switch to a pod-grid
  CSS layout above a width breakpoint.
- `railStackHtml(s)` — the stack, always visible in the left rail rather
  than an overlay, with recently-resolved entries lingering briefly as
  greyed-out "ghosts" (`resolvedGhosts`) so it stays visible what just
  happened even though solo sessions auto-drain the stack immediately.

Every action-producing element carries a `data-action='{"type":...}'`
attribute holding the exact JSON to send; `wire()` attaches one delegated
listener (`root.querySelectorAll('[data-action]')`) that parses it and calls
`act(action)`. `act()` — and the busier `withBusy()` wrapper around it — is
the single choke point every gameplay request goes through: it flips a
`busy` flag, re-renders (disabling controls), sends the action through the
mode's `transport` (see below), and re-renders again on the response. A
past bug class here is worth knowing about: if anything inside a `render()`
call throws (e.g. reading a field a stale view no longer has), `withBusy`'s
`finally` never gets to flip `busy` back off correctly and the whole board
can wedge with every control disabled — this happened for real (a `t` vs
`tl` typo in a spell-type label) and is why `withBusy`'s error path was
hardened; see the "Board lock" note in `Done_Frontend.md` if extending this
pattern.

Cards are also draggable: any tile with a playable action becomes
`draggable="true"`, and dropping it on a highlighted valid target (a
battlefield, another permanent, a player's banner) fires the same action
`act()` would — `dragActionsForInstance`/`dragTargetsForActions`/
`executeDroppedAction` reuse the identical `legal_actions` data the button
path does, so drag-and-drop is a second input method for the same
server-validated actions, not a separate permission system.

**Four modes drive one board.** `goldfishView.js`, `soloView.js`,
`multiplayerView.js`, and `replayView.js`'s play mode each call
`createGameBoardView({...})` and supply their own `transport` (how an
action reaches the server) plus a few mode-specific toggles:

- Goldfish/Replay use the default REST transport (`sendGameAction`/
  `rewindGame` from `api.js`) and leave `allowRewind`/`allowFastForward` at
  their default `true` — solo-practice affordances.
- Multiplayer supplies its own `transport.sendAction`, which posts to
  `POST /api/multiplayer/games/{id}/action` and deliberately returns no
  `data` — the repaint instead comes from the pushed view on `/ws/lobby`
  (`lobbySocket.js`), so every seat repaints from the one message the
  server actually broadcast rather than one client painting its own HTTP
  reply ahead of everyone else. It also sets `allowRewind`/
  `allowFastForward` to `false` (one player can't unilaterally undo a
  shared game, and fast-forwarding through steps would skip an opponent's
  response windows) and supplies `seatStatus` so a dropped player's banner
  can show as visibly absent.
- `extraControls` (a function of `busy`, so it can disable buttons live)
  lets each caller append its own toolbar buttons — goldfish's "Als Replay
  speichern"/"Beenden", multiplayer's per-seat controls — without the
  shared board needing to know about them.

Card identification while hovering — a tooltip with the full card image,
oracle text, and mana cost — is handled globally by
`frontend/src/js/cardHoverDetail.js`: any element anywhere in the app with a
`data-hover-card="<name>"` attribute gets this for free via one delegated
`document`-level listener, no per-view wiring needed. The board's card
tiles all carry this attribute; so does the card-cache/deck-import list
view, which instead renders full card tiles directly with
`frontend/src/js/cardTile.js` (mana-cost-to-emoji rendering, oracle-text
formatting) — that module is shared infrastructure for "show a card
properly," not itself part of the interactive board.

User-facing labels (button text, badges, status messages) are pulled
through `t()`/`tPlural()` from `frontend/src/js/i18n.js`, which resolves
against `locales/en.js`/`locales/de.js` (English is the default; German is
an opt-in switch on the Einstellungen tab that reloads the page) — MTG
keyword names themselves (Flying, Trample, …) are never translated. This
document doesn't re-derive the i18n mechanism; see the wiring in
`i18n.js` if you need it.

---

# PART 4: TARGETING UI

Targeting is a distinct UI mode, not inline within the action button click.
When a `cast_spell`/`activate_ability` legal-action entry carries
`requires_target: true`, its button doesn't call `act()` directly — it
calls `prepareCastTargeting(action)`, which populates the module-level
`castTargeting` state (`{ instanceId, requirements, reqIndex, targets, ... }`)
and re-renders. While `castTargeting` is set, `render()` overlays
`castTargetModalHtml()`: a modal listing every legal option for the current
requirement as its own button (each carrying `data-hover-card` so the
player can inspect it before picking), with a "✕ Abbrechen" escape hatch and
a "∅ Kein Ziel" decline button for an optional requirement. Picking an
option advances `reqIndex`; once every requirement in the spell/ability's
`targets` list has an answer, the assembled action is sent through `act()`
exactly like any other action.

Multi-target requirements (`count > 1`/`count_max`) are expanded
client-side into one modal round per pick (`expandMultiTargetRequirements`),
reusing the same "pick one from a pool, one at a time" flow a cost choice
like "tap two untapped Elves you control" (RULE 602.1) also uses — the
picks are grouped back into per-requirement `target_groups` before sending,
so a spell like Epic Confrontation (pump one creature, then fight it against
another) can't have both halves land on the same permanent. `distinct_
controllers` (RULE 109.5-adjacent "N target creatures controlled by
different players") excludes already-picked controllers from later rounds
the same way.

Targeting also has a second input path: dragging a card whose action
`requires_target` onto a highlighted valid target fires the same single-
target action directly (`executeDroppedAction`), skipping the modal
entirely when there's exactly one target to choose (a multi-target spell
still opens the modal after the drop). Board overlays make legality visible
at rest, not just mid-drag: any permanent currently the target of something
on the stack gets a 🎯 badge and highlighted border (`updateTargetOverlays`,
derived fresh from `state.stack[*].targets` every render), and two
permanents each targeting the other (a mutual Fight, say) get a distinct
"mutual target" border.

Two other choice shapes reuse this same modal-overlay pattern rather than
being a special case: **cost choices** (RULE 602.1 — "tap N untapped
`<type>`s", "Sacrifice a `<type>`", a discard-as-additional-cost) open the
identical picker UI with a different heading/glyph, since the player's own
choice of *which* permanent pays is not a RULE 115 target; and **pending
choices** the engine opens mid-resolution (search, scry/surveil, cascade,
replacement-effect ordering, trigger ordering, …) render as their own modal
(`pendingChoiceHtml`) — a `role="dialog" aria-modal="true"` overlay that
dims the rest of the board (`.goldfish.choosing`), with a "push aside"
escape hatch so a player can check the board before answering. `scry`/
`surveil`/vote-style choices get inline card-face thumbnails instead of bare
buttons; RULE 616.1 replacement-order and RULE 603.3b trigger-order choices
get a drag-and-drop reorderable list instead of a plain option list.

---

# PART 5: TURN-BASED ACTIONS AND PRIORITY — REAL, EASY-TO-GET-WRONG NUANCES

The board's controls change shape depending on whether the session plays
RULE 117 priority out for real (`view.priority.interactive`, on only for
multiplayer — see `CLAUDE.md`'s "RULE 117 priority" section for the full
engine-side behavioural detail; this section only covers what the UI does
with it):

- **Off** (goldfish, Solo gegen Bots, Replay): the toolbar shows "Nächster
  Schritt" (advance) and "Nächste Entscheidung" (fast-forward) buttons —
  the session auto-drains the stack, so there's a literal "advance the
  turn" action to press.
- **On** (multiplayer): there is deliberately no such button
  (`priorityControlsHtml`'s own comment: "a step ends when every player
  passes in succession... so there is deliberately no 'advance the turn'
  button to press"). Instead, **only the player currently holding priority
  may act at all** — enforced server-side in `_dispatch`, not merely by
  omitting buttons client-side — and the client's own gate,
  `hasPriority()`, decides what to even offer: a "Passen" button
  (`passButtonHtml`, relabeled "Stapel auflösen" while the stack is
  non-empty) sits on *that player's own board banner*, right next to the
  cards they're looking at, not in the rail.
- A **per-priority countdown** (`railTimerHtml`/`autoPassArmed`, the left
  rail's shrinking progress bar) runs whenever this client holds priority
  on another player's turn, and on your own turn only in the passive
  upkeep/draw/end steps or whenever there's something on the stack to
  respond to — never during your own main phases/combat, where you're the
  one acting (`reactTimerSuppressedHere`). Its length is a server setting
  (`view.priority.timer_seconds`); any board interaction or its own
  "interrupt" button cancels it for that window.
- A window offering literally nothing but `pass_priority` is passed
  through automatically and silently, no countdown shown — there is
  nothing to interrupt (`skipEmptyArmed`).
- A manual **"End the turn"** button (`endTurnButtonHtml`, next to
  "Passen") is the deliberate opposite of that suppression: once armed, it
  force-passes every priority window this client holds for the rest of the
  current turn, regardless of what `legal_actions` offers — a speed-up for
  a player with nothing left they want to do. It never touches a
  `pending_choice` or a turn-based action, and self-disarms on the next
  genuine board interaction or once the turn actually ends.
- **Declare-blockers is the one action a non-priority-holder can still
  take.** RULE 509.1a makes it a turn-based action the *defending* player
  performs while the *attacker* still holds priority — the UI reflects this
  literally: `blockerPanelHtml` renders whenever `legal_actions` contains a
  `declare_blockers` offer, independent of `hasPriority()`. Blocks are
  assembled locally (one `<select>` per attacker-eligible blocker, held in
  `blockDraft`) and submitted as a single `declare_blockers` action with an
  `assignments` array — never one request per blocker, because RULE
  702.111b's menace family ("can't be blocked except by N or more
  creatures") is only checkable against the whole assignment at once. An
  **empty** `assignments` array is itself a complete, legal answer ("no
  blocks") — `submitBlocks()` is not gated on `blockDraft.size` for exactly
  this reason.
- **Take-backs** (see `CLAUDE.md`'s own section) surface as a button on a
  player's own banner, shown only when the table configured a budget and
  some remains — a table-level convenience distinct from goldfish's
  "Zurücknehmen"/rewind, which multiplayer disables outright.

A player's in-progress selections (an unfinished block assignment, a
mid-target cast) are mirrored to the server as a UI draft
(`saveUiDraft`/`view.ui_draft`) purely so a genuine reconnect can rebuild
the same modal instead of losing it — it's invalidated only when a real
move actually happened (`move_log` growing), never by another player's
socket merely reconnecting and rebroadcasting the same position.

---

# PART 6: WHAT SURVIVED FROM THE OLD PLAN, HONESTLY

A few ideas from the original doc turned out to still be true in spirit, and
are worth naming as such rather than silently dropped:

- **Dense vs. expanded hand/board density**: the old doc sketched a
  dual-pane "small hand strip + one large expanded card" layout. That
  specific design was never built. What *does* exist is a single, simpler
  global density toggle — "Kompaktansicht" (`getCompactView()`/
  `settings.js`, a cookie-backed preference set on the Profil tab per
  `CLAUDE.md`'s board-comfort toggles) that shrinks card tiles and swaps
  full P/T display for a compact badge (`gf-compact-pt`) across the whole
  board, not per-hand.
- **Modest accessibility, not the old doc's full list**: card images carry
  real `alt` text, choice/target modals use `role="dialog" aria-modal="true"`,
  and collapsible sections (zone lists, a "fold this opponent's board"
  toggle) carry `aria-expanded`. There is no dedicated screen-reader mode,
  keyboard-only navigation, high-contrast mode, or font-size control —
  those were aspirational in the old doc and were never built; don't cite
  them as present.

---

# PART 7: WHAT CHANGED FROM THE OLD PLAN

- **No React, no JSX, no virtual DOM.** `CardInHand`/`TargetingPanel` as
  components never existed; the real board is one large `render*(container)`
  controller (`createGameBoardView`) that rebuilds `innerHTML` from template
  literals and re-wires listeners on every change, the same pattern every
  other view in this buildless app uses.
- **No keyboard shortcuts.** The old doc's "1-9 select card / C cast / T
  attack / SPACE pass" scheme was never implemented — a repo-wide search
  turns up no gameplay `keydown` handling anywhere in the board or any mode
  view (Replay's card-search box has an Enter-to-search binding, unrelated
  to gameplay). If this is wanted, it's new work, not a gap in an existing
  feature.
- **"Click card → menu of actions" became "every legal action for this
  card is already a visible button underneath it."** There is no
  intermediate menu step to open before seeing what's available — the
  closest thing to a menu is the multi-defender "choose a defender"
  submenu (`attackControlHtml`) for a creature with more than one legal
  attack target.
- **Targeting stayed a distinct UI mode, exactly as the old doc argued for**
  — just implemented as a modal overlay (`castTargetModalHtml`) plus a
  drag-and-drop alternative, driven by the server's own per-requirement
  `options`, rather than a separate `TargetingPanel` component with its own
  `useState`.
- **The client validates nothing.** This was already the old doc's stated
  principle and remains exactly true: every button, drag-and-drop drop, and
  modal pick sends a plain action object and lets the server accept or
  reject it (`act()`'s `res.ok` branch surfaces a rejection's reason as a
  status message) — the client's only "validation" is not offering a
  button the server didn't send in the first place.

For what's actually open or recently closed on the frontend, see
[`../implementation-state/BACKLOG.md`](../implementation-state/BACKLOG.md)
(categories `VIS`/`PLR` cover most board/UI tickets) and
[`Done_Frontend.md`](../implementation-state/Done_Frontend.md) rather than
trusting this document to stay exhaustive — it describes the shape of the
system, not its current punch list.
