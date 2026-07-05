# Frontend TODO

Open frontend items. Completed work has moved to
[Done_Frontend.md](Done_Frontend.md) (section headers there mirror
these). No Node/npm on this machine, so there's no JS linter/test runner
and no way to drive a real browser — changes are verified by reading the
code plus replaying the equivalent API calls against a running backend,
**not** by an actual rendered page (see "Cleanup / polish").

## Import — follow-ups

- [ ] Direct import from external deck builders (Moxfield, Archidekt,
      …) was tried and reverted: fetching `api.moxfield.com` directly
      from the browser hit Cloudflare bot protection (HTTP 403 on the
      deck page, `/download`, and both v2/v3 API endpoints). Revisit once
      the backend can proxy it server-side
      (`GET /api/import/moxfield/{id}`) — still no guarantee it gets past
      bot protection, but removes the browser-CORS obstacle.

## Backend integration

- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Saved decks

- [ ] No rename/duplicate-as-new actions yet — only save (create/update
      via the tracked id) and delete.

## Card display

- [ ] Mana cost emoji don't distinguish hybrid/Phyrexian symbols from
      plain ones (e.g. `{W/U}` renders as a plain ⚪, not "W or U") —
      inherited from the backend's flattened `Card.mana_cost`. The raw
      `mana_cost_string` is now available (see Done "Mana cost model" in
      the backend) and could drive a faithful render.

## Game engine hookup

- [ ] Targeting UI: select target(s) when a spell/ability requires it
      (docs/05 PART 5). Search-your-library *choices* are handled (the
      "🔎 Suche …" panel), but a spell that needs a chosen target on cast
      still can't pick one from the UI.
- [ ] Subset attacker selection: attacking currently swings with **every**
      able creature (one "⚔️ Angreifen (N)" control). Per-creature select
      needs the backend to accumulate declared attackers rather than
      replace them.
- [ ] Activated abilities beyond tap-for-mana — arbitrary costed
      abilities on permanents (docs/05 PART 6). Tap-for-mana (incl. the
      dual-land colour choice) is done.

## Multiplayer

- [ ] Second player / opponent zones. Needs matchmaking or a local
      "load second deck" flow before this can show anything real
      (docs/02 UC4, docs/04 S5).
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
      `POST /api/decks/{id}/analyze` exists (docs/02 UC2, docs/04 Phase 6).
- [ ] Cache indicator ("Analysis from X ago").

## Bot mode (UC5)

- [ ] "Bot Play" vs "Manual Play" selector before a game starts.
- [ ] Visualize bot actions in real time, with a speed control.

## Cleanup / polish

- [ ] Tooling: no Node/npm on this machine, so no linter, formatter, or
      automated JS test runner, and no way to drive a real browser for UI
      verification (no Playwright/chromium-cli either). Logic was verified
      ad hoc via `osascript -l JavaScript` (JavaScriptCore) in the past —
      worth a real test + browser-automation setup once Node is available.
- [ ] Keyboard shortcuts (docs/05 PART 9).
- [ ] Accessibility: alt-text on cards, tab navigation, high-contrast
      mode (docs/05 PART 10).
- [ ] Responsive/mobile layout — only checked at desktop width so far.
