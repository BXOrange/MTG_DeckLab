# Frontend TODO

Open frontend items only — **when an item is finished, move its narrative
into the matching section of
[Done_Frontend.md](../docs/implementation-state/Done_Frontend.md) (section
headers here mirror there) instead of leaving it checked off in place**; a
one-line "moved to Done_Frontend.md, section name" pointer, or deleting the
line outright, is enough — see CLAUDE.md "Conventions & gotchas". No
Node/npm on this machine, so there's no JS linter/test runner
and no way to drive a real browser — changes are verified by reading the
code plus replaying the equivalent API calls against a running backend,
**not** by an actual rendered page (see "Cleanup / polish").

## Import — follow-ups

- [ ] Moxfield import: tried twice (client-side fetch, then a
      server-side proxy) and reverted both times — Cloudflare blocks it
      genuinely (not just a CORS/header issue; confirmed via a live test
      against a real deck id, see `../backend/ToDo_Backend.md` "Import —
      follow-up from the frontend"), so it's parked pending a
      headless-browser fallback or similar, not a quick fix. Archidekt
      import shipped instead (`Done_Frontend.md` "Import").

## Backend integration

- [ ] Error/loading states for network calls (spinner, retry, offline
      message) — see docs/04 C4.

## Saved decks

- [ ] No rename/duplicate-as-new actions yet — only save (create/update
      via the tracked id) and delete.

## Game engine hookup

Targeting UI, activated abilities beyond tap-for-mana, planeswalker loyalty
(abilities + display), Aura/Equipment attachment UX, and the conditional-land
prompt all shipped — moved to
[Done_Frontend.md](../docs/implementation-state/Done_Frontend.md) "Game
engine hookup".

- [ ] Subset attacker selection: attacking currently swings with **every**
      able creature (one "⚔️ Angreifen (N)" control). Per-creature select
      needs the backend to accumulate declared attackers rather than
      replace them.
- [ ] Restricted-mana display: a mana ability's RULE 605.3a "Spend this
      mana only to cast a creature spell" restriction is now tracked
      server-side (`models/mana_pool.py`'s tagged `restricted` lots,
      `Player.to_dict`'s additive `mana_pool.restricted` key) but the
      board's mana-pool readout doesn't distinguish it from ordinary mana
      yet — a player can't currently see *which* floating mana is
      restricted, or to what.
- [ ] "Any combination of colors" split UI: a `tap_for_mana` action for
      such an ability (RULE 605.1a — Flamebraider/Gwenna/Smokebraider/
      Selvala) now carries `any_combination: true` and `combination_total`
      (`GameEngine.legal_actions`), and the action accepts a `color_split`
      dict (`{colour: count}` summing to the total,
      `services/game_session.py`), but there's no UI to build one yet —
      the board still only offers the existing per-colour buttons (a
      legal but inflexible single-colour tap).
- [ ] Hand-zone mana abilities ("Exile this card from your hand: Add …",
      RULE 605.1a — Elvish/Simian Spirit Guide) have a working backend
      path now (`GameEngine.activate_hand_mana_ability`, a new
      `activate_hand_mana` legal-action kind alongside `tap_for_mana`),
      but the board has no UI trigger for it — a card in hand can only be
      played/cast today, not exiled for mana.

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

- [ ] Tooling: no Node/npm on this machine, so no linter, formatter, or
      automated JS test runner, and no way to drive a real browser for UI
      verification (no Playwright/chromium-cli either). Logic was verified
      ad hoc via `osascript -l JavaScript` (JavaScriptCore) in the past —
      worth a real test + browser-automation setup once Node is available.
- [ ] Keyboard shortcuts (docs/05 PART 9).
- [ ] Accessibility: alt-text on cards, tab navigation, high-contrast
      mode (docs/05 PART 10).
- [ ] Responsive/mobile layout — only checked at desktop width so far.
