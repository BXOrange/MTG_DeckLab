# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Replaces the former
per-half `ToDo_Backend.md` / `ToDo_Frontend.md`, which no longer exist.

Three kinds of document, kept strictly apart — put a new line in the right
one:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | Append-only. What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the indefinite parser tail. |

**Closing a ticket = deleting it from this file** and appending its narrative
to the matching `Done_*.md` section. Never leave a `[x]`, a "shipped" note,
or a "moved to Done" pointer here — this file is read in full, often, so
anything finished that stays costs every future read. If only part of a
ticket is done, keep only the part that isn't.

Ticket ids are stable; reuse a retired id only for the same subject.
Plan-level sequencing lives in
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 (LLM + presentation) |

---

## ENG — Game engine

(none open)

## PAR — Parser

- **PAR-12 · The indefinite long tail.** Strategy, current coverage, and
  worked examples: [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) — split into
  two tracks there, **basic mechanics** (generic shapes, worked by raw
  cache-wide yield) and **set-specific mechanics** (one expansion/precon's
  own signature keyword, worked deck-first against a saved deck's actual
  commander/product). Not a ticket that can be "closed" — a standing
  program. Planechase (901)/Archenemy (904) plane/scheme card *bodies* live
  here too (13/309 measured 2026-08-04) — their trigger conditions are
  recognized, but the bodies are exotic even by tail standards, so this is
  ordinary long-tail work with a known card list, not a distinct gap.
  (Reaching a Planechase/Archenemy/Vanguard table at all is wired up end to
  end — Setup's format picker, `services/lobby.py`, `api/multiplayer.py`/
  `api/game.py` — see Done_Backend.md "PLR-13". Vanguard's own remaining
  piece — a per-seat avatar picker, and its avatars' card text — is a
  permanent non-goal, not a queued gap; see the MEC callout below.)

- **PAR-14 · RULE 702 keyword catalogue: ~122 of 195 registered keywords
  are recognized-but-inert.** A 2026-08-27 systematic audit (prompted by
  finding Station/Toxic both claimed "implemented" by `CLAUDE.md` while
  actually inert or non-existent — Toxic has since shipped for real, see
  `Done_Backend.md`) checked every row in `parser/oracle/catalogue/
  keywords.py` (195 total, not 194) against real `game/` consumers, not
  just the parser's own `MODELED` verdict — the coverage gate only checks
  that a keyword *parses*, not that anything downstream reads it, so a
  bare `[keyword]` spec silently passes as "done" forever. Result: **~70
  fully working, ~122 recognized-but-inert or unenforced, ~3
  hand-authored-only**. The set-specific portion of that 122 (one
  expansion each, e.g. Job Select/Final Fantasy, Web-slinging/Spider-Man)
  is now tracked in [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md)'s
  set-specific table instead of here. What's open here is the
  **evergreen** portion — keywords that recur across many sets/years, so
  a fix pays off repeatedly:
  - **Combat-evasion, never enforced** (a real rules violation, not just a
    missing bonus — e.g. a Shroud permanent can currently be freely
    targeted): Shroud (702.18), Fear (702.36), Intimidate (702.13), Skulk
    (702.118), Shadow (702.28). `targeting._targetable_by` and
    `combat.can_block` need a generic hook the same shape `has_hexproof`
    already has, not five hand-rolled checks.
  - **Cost-reduction keywords never wired to the existing generic
    mechanism** (`continuous.self_cost_reduction_for` already handles
    "costs {N} less for each X"-shaped statics for hand-authored cards —
    it just isn't driven by these keywords themselves): Affinity
    (702.41), Delve (702.66), Convoke (702.51), Improvise (702.126).
  - **Triggered abilities with zero consumer**: Prowess (702.108, ~92
    cache cards — one of the most-reprinted keywords in modern Magic),
    Exalted (702.83, ~36 cards incl. cEDH staples Rafiq/Qasali
    Pridemage/Noble Hierarch), Battle Cry (702.91), Mentor (702.134).
  - **Death/graveyard-adjacent, zero implementation**: Undying (702.93),
    Persist (702.79) — even a hand-authored *grant* of "undying"
    (`ability_catalogue/entries_003.py`) currently does nothing, since no
    death-replacement code anywhere checks for it; Unearth (702.84),
    Embalm (702.128), Eternalize (702.129), Dredge (702.52).
  - **Cast-alternative/timing keywords, zero implementation**: Madness
    (702.35), Miracle (702.94), Ninjutsu (702.49, a real Ninja-tribal
    mechanic), Bestow (702.103), Dash (702.109), Backup (702.165 — a
    counter-placement keyword, confirmed via `parser_probe.py card "Bola
    Slinger"`: bare `[keyword]`, no counters ever placed).
  Full table (all 195 rows, categorized, with file:line evidence per
  bucket) is in the audit's own report — not reproduced here since this
  file stays open-scope-only; re-derive via the same method
  (`parser_probe.py card "<name>"` per keyword, cross-referenced against
  `game/combat.py`'s `COMBAT_KEYWORDS`, `game/effect_binder.py`'s
  `attach_keyword`/`_KEYWORD_TRIGGERED_BUILDERS`) rather than trusting
  this list to stay current as more keywords get built. Each bucket above
  is independently shippable — no shared blocking primitive ties them
  together, unlike Station's/Amass's own single-mechanism builds.

## MEC — Game mechanics

> **Permanent non-goals** (never to be built, not gaps): Stickers (RULE
> 123) and Attractions (RULE 717) — `gate.parse_oracle` classifies mentions
> of the former `NEVER_SUPPORTED`, a verdict kept out of both the coverage
> count and the backlog ranking. **Vanguard (RULE 902) beyond its already-
> shipped hand-size/life-total modifiers** — its ~107 avatars are a small,
> long-retired supplemental-product pool (not a real deck, no set is
> designed around it today), so neither a per-seat avatar picker (every
> seat just gets a random avatar — the modifiers apply regardless of which
> one) nor parser handlers for individual avatars' extra rules text will be
> built. Structurally enforced already, not just documented:
> `scripts/import_bulk.py`'s `_SKIP_LAYOUTS` drops the Scryfall `vanguard`
> layout from `cache/db/cards.db` entirely (0 of the 34,208 cached cards),
> so avatar text can never surface in `coverage_report.py`/
> `processing_list.py`'s ranking in the first place — the committed
> `services/variant_card_database.py` pool they live in instead is never
> read by either. `game/effect_binder.bind_from_catalogue` still binds
> whatever a general-purpose handler happens to already recognize when an
> avatar is actually boarded (RULE 902.2), same as any other unregistered
> card — that's ordinary runtime behavior, not scheduled work, and needs no
> special-casing to stay that way.

(none open)

## PLR — Player management

- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck. Also what actually
  closes the collision gap the PLR-4 client-token stub (`services/
  lobby.py`'s `client_token`, `Done_Backend.md` "Client-token identity
  stub") only covers halfway: that token is unsigned, client-trusted data —
  copy/clear/forge it and nothing notices — and a client that has never
  opened Profil still resolves purely by name, the original "two people
  sharing a name share a seat" collision. Fine for a LAN table, not for
  anything public.
- **PLR-14 · Team variants (RULE 809/810/811).** Two-Headed Giant, Emperor
  and Grand Melee are the part of CR 8 that `models/game_format.py`
  deliberately doesn't model: unlike the RULE 9 variants (which add a card
  pool beside the game) these change the **turn structure itself** — a
  shared life total, two players taking one turn together, a "defending
  team" in combat, RULE 810.8's shared damage assignment. That's a turn-loop
  and combat project, not a format record. The seats it needs exist now (a
  table opens for up to four), so what's left is genuinely the turn loop;
  reaching it from the UI follows the same already-shipped format-picker
  pattern the RULE 9 variants use (Done_Backend.md "PLR-13").

## VIS — Visuals

- **VIS-4 · Chat / emotes at the table.**
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9.
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.

> No Node/npm on this machine, so there is no JS linter/formatter/typecheck
> — but real-browser verification *is* available: Playwright (Python) lives
> in `backend/venv` and drives a real Chromium against the static frontend
> server plus a running backend. Use it for any non-trivial UI change
> instead of reading code and replaying API calls by hand.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-1 · `POST /api/decks/{id}/analyze`.** Claude API integration, prompt
  templates, structured output parsing, caching (docs/02 UC2, docs/04 Phase
  6). `Deck.analysis_id` is reserved to link a saved deck to the result, but
  no `Analysis` model/table exists — design it alongside the endpoint rather
  than assuming the reserved field's shape is final.
- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. Blocked on [ANA-1].
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  Blocked on [ANA-1].
