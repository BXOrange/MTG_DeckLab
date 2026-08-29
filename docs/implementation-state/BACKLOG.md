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

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, current coverage, and worked examples all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) — not duplicated here. Two
  tracks: **basic mechanics** (generic shapes, worked by raw cache-wide
  yield) and **set-specific mechanics** (one expansion/precon's own
  signature keyword, worked deck-first against a saved deck's actual
  commander/product). As of 2026-08-28 the basic-mechanics track's easy
  big wins are **exhausted**: a fresh cache-wide `rank` top-N verified
  card-by-card with `parser_probe.py blocked` came back all-already-claimed
  (see `PARSER_LONG_TAIL.md`'s "verify before sizing … at scale" lesson —
  PAR-20, now closed, was the dated finding; its one concrete follow-up,
  the RULE 604.3 CDA-P/T handler, shipped at PARSER_VERSION 105). So the
  **deck-first set-specific track is the primary one now** — audit a real
  saved deck's card list rather than re-mining `rank`. Planechase
  (901)/Archenemy (904) plane/scheme card *bodies* (13/309 measured
  2026-08-04) are ordinary long-tail work with a known card list under
  this same pointer, not a distinct ticket — their trigger conditions are
  already recognized, only the bodies are exotic even by tail standards.
  (Reaching a Planechase/Archenemy/Vanguard table at all is wired up end
  to end already — see Done_Backend.md "PLR-13"; Vanguard's own avatar
  picker/text is a permanent non-goal, see the MEC callout below.)

  > **Ticket-id note:** every number from `PAR-1` through `PAR-28` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords). The only open parser ticket below is `PAR-29`.

- **PAR-29 · RULE 701 keyword actions with no parser handler.** The
  RULE 701 audit that PAR-21 asked for is done (2026-08-29,
  `Done_Backend.md` "PAR-21: RULE 701 keyword-action audit" — it also
  closed Connive and Discover, which already had shipped engine effects).
  **Explore** (RULE 701.44) was then built end-to-end (2026-08-29,
  `Done_Backend.md` "Explore" — a new `RulesEngine.explore` primitive +
  `EventType.EXPLORED` + `explore_bin` choice + oracle handlers, +22
  cards); its only residue is a trigger-condition parser row for
  "whenever ~/a creature you control explores, `<effect>`" (the
  `EXPLORED` event fires already, nothing reads it), grouped with the
  other RULE 603.1 trigger-vocabulary gaps rather than tracked here.
  **Populate** (RULE 701.36) followed the same day (2026-08-29,
  `Done_Backend.md` "Populate" — `RulesEngine.populate` on the existing
  `copy_permanent` path + a `populate` "which token?" choice + one
  bare-word handler, +14 cards); no residue beyond "populate X times"
  (Full Flowering, a dynamic repeat count) and cards carrying a second
  unmodeled clause alongside their now-real "populate".
  **Bolster** (RULE 701.39) + **Support** (RULE 701.41) followed
  (2026-08-29, `Done_Backend.md` "Bolster + Support" — `RulesEngine.
  bolster` (least-toughness selector + a `bolster` tie-break choice) is a
  new primitive; Support is a parser alias onto the existing `add_counters`
  "up to N target creatures" spec, +25 cards); residue is the dynamic
  "bolster X" / "support X" amount and a couple of second-clause cards.
  What remains below is the rest of the audit's gaps. Each is an ordinary
  effect-grammar gap, *not* a "keyword ability missing from a registry";
  most need a new engine primitive before a handler is worth writing, so
  most belong under `MEC` once picked up. Solo-blocker counts are
  cache-wide from `parser_probe.py`.
  - **Needs an engine primitive first:** Vote (701.38, ~28 — the voting subsystem,
    RULE 701.38a APNAP-order choice); Clash (701.30, ~33 — reveal top, may
    bottom it, "if you win" = higher mana value); Detain (701.35, ~11 —
    an "until your next turn, can't attack/block, abilities can't be
    activated" designation, shaped like goad); Learn (701.48, ~16 — discard-may→draw, else Lesson from
    outside the game); Incubate as a generic `incubate N` (701.53, ~25 —
    Incubator DFC token with N +1/+1 counters; hand-authored per-card
    only today); Face a Villainous Choice (701.55, ~11 — a forced modal
    on an opponent); Collect Evidence (701.59, ~12 — additional cost:
    exile graveyard cards totalling mana value ≥ N); Suspect (701.60, ~14
    — menace + "can't block" designation); Forage (701.61, ~5); Endure
    (701.63 — N/N Spirit *or* N +1/+1 counters); Blight as a generic
    `blight N` (701.68, ~13 — N -1/-1 counters on a creature you control;
    hand-authored per-card only); Time Travel (701.56, ~3 — suspend-
    adjacent); Behold (701.4, ~6 — "behold a `<quality>`" additional
    cost); Harness (701.64 — a monstrous-style marker designation), Heal
    (701.69 — remove marked damage), Recruit (701.70 — draw/discard→1/1
    token); the Avatar bending quartet — Airbend (701.65), Earthbend
    (701.66, ~18), Waterbend (701.67, ~11 — a "tap artifacts/creatures
    for generic mana" cost mechanic), Firebend.
  - **Parser-shaped only (engine already fine):** "connive N" (701.50d —
    `ConniveEffect` needs a count parameter); standalone "double/triple
    target creature's power and toughness" (701.10/11 — damage- and
    token/counter-doubling are already covered); a general "exchange
    control of `<X>`" / "exchange life totals" handler (701.12 — only
    per-card hand-authored today, Gilded Drake-shaped).
  - **Not gaps** (real handler verified action-by-action, not an
    incidental `MODELED`): Attach, Counter, Create, Destroy, Discard,
    Exile, Fight, Goad, Investigate, Mill, Regenerate, Scry, Search,
    Shuffle, Surveil, Tap/Untap, Transform/Convert, Proliferate,
    Monstrosity, Adapt, Amass, Manifest/Cloak, Manifest Dread, Venture,
    The Ring Tempts You, Connive, Discover, Explore, Populate, Bolster,
    Support — plus engine-action verbs with
    no oracle grammar (Activate/Cast/Play) and variant-subsystem ones
    (Planeswalk/Set in Motion/Abandon, Meld). Assemble (701.45) is out of
    the CR; Open an Attraction / Roll to Visit (701.51/52) are the
    Attractions non-goal.

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
