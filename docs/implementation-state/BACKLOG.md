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
  than forced to completion in one sitting given the size. Current state
  (2026-08-11, tenth pass): **Ojer 45/77, Rocco 74/98, Glarb Bloomsday
  80/100, staples 176/215, staples 2 421/607, M-K 84/97, Kinnan 81/100**
  (unique-card total 478/722) — re-measure rather than trusting these
  numbers as they age; the per-deck *totals* themselves also drift run to
  run since these are live saved decks a user can keep editing, not a
  frozen fixture. Worklog detail for what's shipped so far — batch by
  batch, why each piece is built the way it is — is in `Done_Backend.md`'s
  "seven 'cEDH'-named saved decks" entries, not here.

  The tenth pass closed four of the fourth pass's own "broader gaps,
  needs real design" list (below), each turning out to need no new
  primitive at all — RULE 613.6's `control_count`/`type_change`, RULE
  601.2c's mass-selector/count-selector families, and RULE 500.4's own
  turn-sequence-as-data design (`phases.default_turn_sequence`'s docstring
  had already anticipated the one genuinely new piece) all already
  existed; the work was oracle-text handlers plus the odd wiring gap
  (`DealDamageEffect._apply_selector` never having read `amount_from_
  count_selector`, `_matches_sacrifice_type`'s "any permanent" catch-all).
  Full detail in `Done_Backend.md`'s "MEC-12 tenth pass" entry. The
  eighth/ninth passes' own diagnosed-open items are unchanged: Redirect
  Lightning's "pay 5 life **or** pay `{2}`" additional cost (confirmed
  cache-wide singleton — hand-author next time), Kutzil's second ability
  (derived-vs-printed-power trigger), and Grafdigger's Cage/Weathered
  Runestone's zone-cast-restriction pair (two genuinely new primitives —
  `RulesEngine._move_to_graveyard` is *not* the single choke point its own
  docstring frames it as; `mill`/`discard`/`discard_choice` all move cards
  to a graveyard with their own direct `player.graveyard.append(obj)`,
  bypassing it entirely, so "any card, from anywhere" needs the redirect
  added at every one of those sites, not just the one already-hooked
  permanent-death path — a real unification project, not a quick
  extension).

  Broader gaps the fourth pass's full-pool sweep surfaced, each blocking a
  double-digit slice of the remaining residue and needing real design, not
  just a handler: a general **"players can't `<verb>`"** cross-cutting
  family (search libraries/gain life/draw more than N — Leonin Arbiter/
  Rampaging Ferocidon/Narset-Parter-of-Veils-shaped/Stasis, each needing
  enforcement wired into the real search/life-gain/draw call sites, not a
  single shared primitive — untap's own member of this family shipped as
  the generalized `active_untap_caps`, so Stasis's "players skip their
  untap steps" is the only one of the original four still open here); a
  **"players can't cast spells from graveyards or libraries" +
  "`<type>` cards in graveyards/libraries can't enter the battlefield"**
  pair (Grafdigger's Cage/Weathered Runestone — see this ticket's own
  narrative above for why it's a real multi-site unification, not a
  regex); and the wider **"copy a creature except it also `<X>`"** family
  beyond the couple of shapes already hand-authored. Devotion/phasing-out/
  extra-combat/alt-cost all closed this pass (see above) — each still has
  its own smaller residue worth a future ticket if picked up again: **a
  general "X is the number of `<noun phrase>` you control" count-amount
  resolver** (400+ cache-wide solo-blocked cards, `parser_probe.py blocked
  "where x is the number of"` — devotion/Downhill Charge's own land-count
  pump only needed a narrow one-off regex each; Nykthos, Shrine to Nyx's
  mana ability (amount depends on a colour *chosen by the same ability* —
  a new choice+amount coupling); "devotion to hybrid" (Blended Twistling —
  any hybrid pip counts, not a colour); the "intervening if" trigger-
  condition family ("whenever ~ attacks, **if it's the first combat phase
  of the turn**, …" — Karlach/Finest Hour/Genji Glove-shaped, ~20 more
  cache-wide extra-combat cards alone); RULE 702.19 **Exert** (Combat
  Celebrant's own gate, unbuilt as a mechanic at all); a creature-spell
  route for `alt_cost` (the Bringer cycle's "You may pay `<mana>`
  rather than pay this spell's mana cost." — the *engine* side is wired
  and tested, but `parser/oracle/segmenter.py`'s `allow_spell_effect`
  standalone-line special cases are gated to instants/sorceries only,
  `gate.py`'s `_is_spell`); and Snuff Out's own sibling shapes (Dark
  Triumph's "if you control a Swamp, you may **sacrifice a creature**
  rather than pay…" — a compound condition+sacrifice `alt_cost`, and the
  broader "you may discard a `<type>` card"/"you may pay `<mana>` **and**
  `<other cost>`" alt-cost shapes `parser_probe.py blocked "rather than
  pay this spell"` still lists ~40 cards against). None of these should be
  built *for* this ticket alone — each is worth its own ticket once picked
  up, scoped against the wider cache via `parser_probe.py`/`engine_bench.py
  cards`, not just this pool's count.

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
