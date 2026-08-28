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
  commander/product). `PAR-20` below is 2026-08-28's concrete finding
  about where the basic-mechanics track currently stands. Planechase
  (901)/Archenemy (904) plane/scheme card *bodies* (13/309 measured
  2026-08-04) are ordinary long-tail work with a known card list under
  this same pointer, not a distinct ticket — their trigger conditions are
  already recognized, only the bodies are exotic even by tail standards.
  (Reaching a Planechase/Archenemy/Vanguard table at all is wired up end
  to end already — see Done_Backend.md "PLR-13"; Vanguard's own avatar
  picker/text is a permanent non-goal, see the MEC callout below.)

  > **Ticket-id note:** every number from `PAR-1` through `PAR-19` is
  > already a real, shipped, cross-referenced ticket elsewhere in this
  > codebase (grep before reusing one — `PAR-14`, for one, is RULE 603.2's
  > once-per-turn trigger limiter, `Done_Backend.md`, nothing to do with
  > keywords). The tickets below correctly start at `PAR-20`.

- **PAR-20 · Parsable Grammar: the cache-wide basic-mechanics track has run
  out of single big wins — verify before sizing, deck-first is now the
  better track.** `rank`'s raw top-25 (2026-08-28, PARSER_VERSION 99) still
  *lists* count-40+ templates ("choose N —", "you get an emblem with
  `<name>`", "this spell costs `<cost>` more to cast for each target beyond
  the first", O-Ring-shaped "exile target nonland permanent ... until ~
  leaves the battlefield", "enchanted creature has `<name>`", the
  2011+-template werewolf transform condition) — but `parser_probe.py
  blocked` on all six found the clause each one names is **already
  correctly claimed** by existing grammar; every one of those cards'
  *real* blocker is a distinct, unique, one-off co-resident clause with no
  shared pattern (`blocked`'s own "what else blocks those cards" residue
  comes back essentially all count-1). This is a real, dated finding, not
  a guess — don't re-verify the same six from scratch, but don't trust a
  fresh `rank` top-N either without re-running `blocked` on it, since this
  is exactly the failure mode `PARSER_LONG_TAIL.md`'s own "lessons"
  section already warns about, now confirmed at unusual scale. Two
  concrete follow-ups, both session-sized: (1) check whether "`<name>`'s
  power and toughness are each equal to the number of cards in your hand"
  and "...the number of lands you control" (two independently-occurring
  CDA templates in that same residue) already generalize for free via the
  existing count-selector CDA support (MEC-27's "General Count-Amount
  Resolver") — if not, a small paired handler; (2) given the cache-wide
  track's diminishing returns, the better next session is switching
  primary effort to `PARSER_LONG_TAIL.md`'s own **deck-first** track —
  audit a real saved deck (a cluster of cards someone actually plays is
  far more likely to share a real, unfixed pattern than the aggregate
  cache is at this point) rather than mining `rank`'s cache-wide top-N
  again.

- **PAR-21 · Missing Keywords: RULE 702 catalogue is numerically complete;
  RULE 701 keyword actions need their own audit.** Verified 2026-08-28:
  `parser/oracle/catalogue/keywords.py`'s 195 rows cover all 193 distinct
  RULE 702.2–702.194 rule numbers with **zero gaps** (cross-checked
  programmatically against the full numeric range) — "a real RULE 702
  keyword ability entirely absent from the registry" is not an open
  problem. What's genuinely unaudited: RULE 701 **keyword actions** (Scry,
  Mill, Investigate, Explore, Fight, …) are deliberately *not* tracked via
  this catalogue at all — they're ordinary verbs recognized by
  `catalogue/handlers.py`'s effect grammar, a structurally different
  mechanism, and most are believed covered per this doc's own extensive
  feature list, but that belief has never been exhaustively cross-checked
  action-by-action. Session-workable: walk the full RULE 701 keyword-action
  list (`docs/Reference/rules_wiki/`) against `handlers.py`, confirm each
  has a real handler (not just that some card using it happens to be
  `MODELED` for an unrelated reason), and report any genuine gap found.

- **PAR-22 · Combat-evasion keywords never enforced (real rules
  violations, not missing bonuses).** Shroud (702.18) — a Shroud permanent
  can currently be freely targeted; Fear (702.36), Intimidate (702.13),
  Skulk (702.118), Shadow (702.28) — `combat.can_block` only ever checks
  flying/reach/protection. `targeting._targetable_by` and `combat.can_block`
  need a generic hook the same shape `has_hexproof` already has, not five
  hand-rolled hard-coded checks. (One of the five buckets split out of the
  2026-08-27 RULE 702 keyword audit, `Done_Backend.md`'s "MEC-30"-adjacent
  entries and the audit's own full findings — see `PAR-23`/`PAR-24`/
  `PAR-25`/`PAR-26` below for the rest.)

- **PAR-23 · Cost-reduction keywords never wired to the existing generic
  mechanism.** `continuous.self_cost_reduction_for` already handles "costs
  `{N}` less for each X"-shaped statics for hand-authored cards — it just
  isn't driven by these keywords themselves yet: Affinity (702.41), Delve
  (702.66), Convoke (702.51), Improvise (702.126).

- **PAR-24 · Triggered keyword abilities with zero engine consumer.**
  Prowess (702.108, ~92 cache cards — one of the most-reprinted keywords
  in modern Magic), Exalted (702.83, ~36 cards incl. cEDH staples
  Rafiq/Qasali Pridemage/Noble Hierarch), Battle Cry (702.91), Mentor
  (702.134).

- **PAR-25 · Death/graveyard keyword family, zero implementation.**
  Undying (702.93), Persist (702.79) — even a hand-authored *grant* of
  "undying" (`ability_catalogue/entries_003.py`) currently does nothing,
  since no death-replacement code anywhere checks for it; Unearth
  (702.84), Embalm (702.128), Eternalize (702.129), Dredge (702.52).

- **PAR-26 · Cast-alternative/timing keyword family, zero implementation.**
  Madness (702.35), Miracle (702.94), Ninjutsu (702.49, a real Ninja-tribal
  mechanic), Bestow (702.103), Dash (702.109), Backup (702.165 — a
  counter-placement keyword, confirmed via `parser_probe.py card "Bola
  Slinger"`: bare `[keyword]`, no counters ever placed).

  (PAR-22 through PAR-26 are the **evergreen** portion of the 2026-08-27
  audit's ~122-of-195-inert finding — the set-specific portion, one
  expansion each, is tracked in `PARSER_LONG_TAIL.md`'s own set-specific
  table instead. Each ticket is independently shippable — no shared
  blocking primitive ties them together, unlike Station's/Amass's own
  single-mechanism builds. The audit's full table — all 195 rows,
  categorized, with file:line evidence per bucket — isn't reproduced here
  since this file stays open-scope-only; re-derive via `parser_probe.py
  card "<name>"` per keyword, cross-referenced against `game/combat.py`'s
  `COMBAT_KEYWORDS` and `game/effect_binder.py`'s `attach_keyword`/
  `_KEYWORD_TRIGGERED_BUILDERS`, rather than trusting this list to stay
  current as more keywords get built.)

- **PAR-28 · "Keyword — `<activated/triggered ability>`" label family
  (deferred out of PAR-27's recognition pass).** RULE 702 keywords that
  print a RULE 207.2c-style em-dash label introducing a *real* ability
  whose behaviour also carries the keyword's own restriction: **Boast**
  (702.142, once per turn + only if the creature attacked — Eradicator
  Valkyrie, Varragoth), **Exhaust** (702.177, once per game — Greasewrench
  Goblin, Mindspring Merfolk, Winter Cursed Rider, Echoing Cavern,
  Rebellious Captives, Riverchurn Monument), **Solved** (702.169,
  conditional on the Case being solved — Case of the Filched Falcon / …
  Locked Hothouse / … Pilfered Proof), **Max Speed** (~702.178, active
  only at max speed — Slick Imitator, Far Fortune, The Mystery Raceway),
  **Power-up** (Marvel — Hercules, Immortus, Molly Hayes, Nick Fury, White
  Tiger), **Forecast** (702.57, activated from hand during upkeep, once
  per turn — the Dissension cycle, ~6 cards). PAR-27 deliberately did
  **not** claim these: stripping the label alone would model a working but
  *unrestricted* ability (freely re-activatable, no timing gate), a
  half-model. The real work is to strip the label **and** bind each
  keyword's restriction (Boast/Exhaust reuse existing once-per-turn /
  once-per-game machinery; Solved reuses the `is_solved` designation gate;
  Forecast needs a from-hand activation zone). Only the two Boast cards are
  SOLO-blocked on the label today (Eradicator Valkyrie, Varragoth); the
  Exhaust/Solved/Power-up/Max Speed cards are additionally blocked on
  unrelated set mechanics, so this is a fidelity/no-half-model ticket more
  than a coverage-number one.
  Set-specific status rows for Exhaust/Solved/Max Speed are in
  `PARSER_LONG_TAIL.md`'s table; this ticket is the consolidated engine/
  parser build across all six.

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
