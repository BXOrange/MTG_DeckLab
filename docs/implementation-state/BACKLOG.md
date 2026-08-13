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

- **MEC-12 · Make the seven "cEDH"-named saved decks/cubes fully playable.**
  User request 2026-08-06: `Ojer cEDH`, `cEDH Rocco`, `[cEDH] Glarb
  Bloomsday`, `cEDH staples`, `cEDH staples 2`, `cEDH M-K`, `cEDH Kinnan` (a
  700+-unique-card pool across the seven, heavy overlap — the same ~40 real
  cEDH staples recur across most of them). **Not** "no deferrals" scope like
  the Eliferate/Imodane batches — tracked here as ordinary open work rather
  than forced to completion in one sitting given the size. **`cEDH Kinnan`
  (100/100) and `cEDH M-K` (97/97) are now fully playable** — closed
  2026-08-13, see `Done_Backend.md`'s "MEC-12: Kinnan and M-K completed"
  entry. **`Ojer cEDH` is now 75/77** — closed 2026-08-13, see
  `Done_Backend.md`'s "MEC-12: Ojer cEDH batch" entry; its own 2 residual
  gaps (`Chandra's Incinerator`'s dynamic cost reduction + an event-target-
  scoped "creature or planeswalker *that damaged player* controls" target
  kind that doesn't exist yet; `Return the Favor`'s RULE 702.172 Spree — a
  genuinely unbuilt per-mode-additional-cost modal-casting mechanic, not
  just an oracle-text gap, since `Escalate`'s own keyword line is equally
  inert — no card in the current pool needs Spree/Escalate built badly
  under time pressure) are real, diagnosed primitive gaps, not oversights;
  build Spree as a real mechanic (RULE 702.172, likely unlocking Escalate's
  RULE 702.53 for free alongside it — same "choose N, pay per choice"
  shape) before attempting either card again. **`cEDH Rocco` is now
  78/98** — a first pass (2026-08-13, see `Done_Backend.md`'s "MEC-12:
  Rocco first pass" entry), not yet finished; its own 20 residual gaps
  span several distinct unbuilt shapes (RULE 702.172 Spree/Escalate again;
  a "power greater than its base power" per-creature qualifier on the
  CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER aggregate; a card's own
  self-referential "cast this from your graveyard **or exile**" permission,
  distinct from the existing granted-by-another-permanent shape;
  "Saddle"/RULE 702.172-adjacent Vehicle crewing add-ons; a cost-payment
  restriction ("can't pay life or sacrifice permanents to cast/activate");
  a same-name ETB-draw-engine qualifier; and others not yet individually
  diagnosed) — re-measure and diagnose fresh rather than assuming this
  list is complete or unchanged. **`[cEDH] Glarb Bloomsday` is now
  88/100** — a first pass (2026-08-13, see `Done_Backend.md`'s "MEC-12:
  Glarb Bloomsday first pass" entry), not finished; its own 12 residual
  gaps span Doomsday's own distinct "exile up to five cards in a pile" (a
  genuinely separate unbuilt mechanic, not a plain search — see the
  "Notable gaps" note elsewhere in this file), Ad Nauseam/Gifts Ungiven/
  Bring to Light's own reveal/choice shapes, Counterbalance's live-
  comparison counter-spell condition, Necropotence's three-clause engine
  (a standing draw-step skip needs a battlefield-lifecycle hook into
  `Player.player_effects` that doesn't exist yet, plus a delayed
  face-down-exile-to-hand shape), Opposition Agent's "you control your
  opponents while they're searching" (a real, unbuilt control-exchange-
  during-a-choice shape), Valley Floodcaller's own trigger (a named-
  subtype-list creature group — `PumpEffect` has no `subtypes` list param
  the way `AddCountersEffect` does), and Nissa/Sylvan Library's own
  multi-step choices — each individually diagnosed, not guessed at.
  Current state of the remaining two (2026-08-13): **staples 183/215,
  staples 2 446/607** — re-measure rather than trusting these numbers as
  they age; the per-deck *totals* themselves also drift run to run since
  these are live saved decks a user can keep editing, not a frozen
  fixture. Worklog detail for what's shipped so far — batch by batch, why
  each piece is built the way it is — is in `Done_Backend.md`'s "seven
  'cEDH'-named saved decks" entries, not here.

  The fourth-through-tenth-pass "broader gaps" this section used to
  describe in detail (Exert, Stasis's untap-skip, devotion-to-hybrid,
  Nykthos's choice+amount coupling, the alt-cost creature-spell gate and
  Snuff Out's siblings, the Grafdigger's Cage pair, copy-except-also, the
  count-amount resolver, and the intervening-if family) all closed in a
  2026-08-12 batch — see `Done_Backend.md`'s "MEC-12: the nine 'broader
  gaps' batch" entry for what shipped and why. The residual/adjacent
  tickets that batch surfaced (MEC-27, MEC-28, MEC-29, PAR-18, PAR-19,
  ENG-29) are now all closed too — see `Done_Backend.md`'s matching
  entries. A narrower gap surfaced while closing MEC-28 (a genuine RULE
  601.2c target-count *range*) was filed as ENG-30 and closed the same
  day — see `Done_Backend.md`'s "ENG-30" entry.

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

- **VIS-1 · Error/loading states** for network calls (spinner, retry,
  offline message). docs/04 C4.
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

- **DB-3 · Commander legality gaps.** No Background / "Friends forever"
  pairing, and no check that a commander is actually legendary.
  `check_commander_legality` covers color identity, the ban list, and plain
  Partner/"Partner with X" only.

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
