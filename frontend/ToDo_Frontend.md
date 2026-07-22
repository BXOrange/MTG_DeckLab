# Frontend TODO

Open frontend items only — **when an item is finished, move its narrative
into the matching section of
[Done_Frontend.md](../docs/implementation-state/Done_Frontend.md) (section
headers here mirror there) instead of leaving it checked off in place**; a
one-line "moved to Done_Frontend.md, section name" pointer, or deleting the
line outright, is enough — see CLAUDE.md "Conventions & gotchas". No
Node/npm on this machine, so there's no JS linter/formatter/typecheck, but
real-browser verification *is* available: Playwright (Python) lives in
`backend/venv`, driving a real Chromium against the static frontend server
plus a running backend (`page.goto`/`.click`/`.screenshot`) — use it for any
non-trivial UI change instead of reading code + replaying API calls.

## Backend integration

- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Saved decks

- [ ] No rename/duplicate-as-new actions yet — only save (create/update
      via the tracked id) and delete.

## Game engine hookup

Targeting UI (incl. declining an optional "up to one target"), activated
abilities beyond tap-for-mana, planeswalker loyalty (abilities + display),
Aura/Equipment attachment UX, the conditional-land prompt, restricted-mana
display, the any-combination-of-colours split builder, the hand-zone mana
ability trigger, and the "may choose not to untap" toggle all shipped —
moved to [Done_Frontend.md](../docs/implementation-state/Done_Frontend.md)
"Game engine hookup".

- [ ] Subset attacker selection: attacking currently swings with **every**
      able creature (one "⚔️ Angreifen (N)" control). Per-creature select
      needs the backend to accumulate declared attackers rather than
      replace them.

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

Static/numeric analysis (mana curve, land archetypes, Command Zone
categories, Bracket-Analyse) is done — see `Done_Frontend.md` "Deck
analysis (UC2)". Still open, blocked on the backend LLM endpoint:

- [ ] Narrative "Analyze deck" results (win conditions, archetype,
      synergies, cohesion score, issues) once
      `POST /api/decks/{id}/analyze` exists (docs/02 UC2, docs/04 Phase 6).
      Would sit alongside the existing static/Bracket sub-tabs, not
      replace them.
- [ ] Cache indicator ("Analysis from X ago") for that LLM result once it
      exists.

## Bot mode (UC5)

- [ ] "Bot Play" vs "Manual Play" selector before a game starts.
- [ ] Visualize bot actions in real time, with a speed control.

## Cleanup / polish

- [ ] Keyboard shortcuts (docs/05 PART 9).
- [ ] Accessibility: alt-text on cards, tab navigation, high-contrast
      mode (docs/05 PART 10).
- [ ] Responsive/mobile layout — only checked at desktop width so far.
