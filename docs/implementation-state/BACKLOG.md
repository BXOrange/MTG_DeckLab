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

- **MEC-12 · Make the seven "cEDH"-named saved decks/cubes fully
  playable.** User request 2026-08-06: `Ojer cEDH`, `cEDH Rocco`, `[cEDH]
  Glarb Bloomsday`, `cEDH staples`, `cEDH staples 2`, `cEDH M-K`, `cEDH
  Kinnan` (700+ unique cards across the seven, heavy overlap). Ordinary
  open work, not "no-deferral" scope forced to one sitting. `cEDH Kinnan`
  (100/100), `cEDH M-K` (97/97), and **`cEDH Rocco` (98/98)** are fully
  playable — see `Done_Backend.md`'s "MEC-12: Kinnan and M-K completed"
  and "MEC-40" entries. Coverage as of 2026-08-19 (re-measure before
  trusting — these are live, user-editable decks):

  | Deck | Coverage | Residual, tracked as |
  | --- | --- | --- |
  | `Ojer cEDH` | 75/77 | Chandra's Incinerator's dynamic cost reduction + a "creature/planeswalker *that damaged player* controls" target kind (doesn't exist); Balin's Tomb is real (the LOTR alt name for Ancient Tomb) but doesn't resolve — see CLAUDE.md's `flavor_name` gotcha, an import/card-database gap, not a parser/engine one. |
  | `cEDH Rocco` | 98/98 | fully playable. |
  | `[cEDH] Glarb Bloomsday` | 92/100 | [MEC-41]. |
  | `cEDH staples` | 202/215 | [MEC-42]. |
  | `cEDH staples 2` | 505/607 | [MEC-43]. |

  Six names in the raw scan (Balamb Garden, Dol Amroth, Jodah the unifier,
  Seymour Guado, Thrum of the Vestige, Zidane Tribal) aren't real Scryfall
  cards — not a gap, don't chase them. Worklog detail for what's shipped —
  batch by batch, why each piece is built the way it is — is in
  `Done_Backend.md`'s "seven 'cEDH'-named saved decks" entries, not here.

- **MEC-41 · `[cEDH] Glarb Bloomsday`'s remaining 8 gaps** (Doomsday closed
  as MEC-37, Necropotence as MEC-38, Opposition Agent as MEC-39, Sylvan
  Library as MEC-40, all 2026-08-19). Ad Nauseam/Gifts Ungiven/Bring to
  Light's own reveal/choice shapes; Counterbalance's live-comparison
  counter-spell condition; Valley Floodcaller's own trigger (a
  named-subtype-list creature group — `PumpEffect` has no `subtypes` list
  param the way `AddCountersEffect` does); Nissa's own multi-step
  choices — each needs individual diagnosis, not a guess.

- **MEC-42 · `cEDH staples`'s remaining 13 gaps.** Abrupt Decay, Cabal
  Ritual, Culling Ritual, Ranger-Captain of Eos, Tinder Wall, and Yasharn
  (shared with `cEDH Rocco`) closed 2026-08-19 as part of MEC-40 (`Done_
  Backend.md`'s "MEC-40 batch 1"/"MEC-40: cEDH Rocco done to completion"
  entries — filed there since the primitives were built chasing `cEDH
  Rocco`'s own ticket, and this deck shares the same cards). Still open:
  Ashling the Limitless, Dauthi Voidwalker, Delay, Derevi Empyrial
  Tactician, Mana Crypt, March of Swirling Mist, Orcish Bowmasters,
  Praetor's Grasp, Sevinne's Reclamation, Teferi Time Raveler, Touch the
  Spirit Realm, Tymna the Weaver — plus Ad Nauseam shared with `[cEDH]
  Glarb Bloomsday` (see [MEC-41]). Delay is confirmed-blocked on RULE
  702.61 Suspend's own time-counter/cast-on-zero mechanism, which has
  never been built (only keyword-recognized) — a real ticket-sized gap on
  its own, not a quick hand-author. None of the rest individually
  diagnosed yet.

- **MEC-43 · `cEDH staples 2`'s undiagnosed remainder** (MEC-31 Spree/
  Escalate, MEC-32 the draw-replacement family, MEC-33 Omen Machine,
  MEC-34 Animate Dead, MEC-35 Leonin Arbiter, MEC-36 Damping Sphere,
  MEC-37 Doomsday, MEC-38 Necropotence, MEC-39 Opposition Agent, MEC-44
  Necromancy, and every card MEC-40 closed for `cEDH Rocco` (Ranger-
  Captain of Eos, Abrupt Decay, Cabal Ritual, Culling Ritual, Tinder Wall,
  Vexing Shusher, Academy Rector, Ajani Nacatl Pariah/Avenger, Allosaurus
  Shepherd, Domri Anarch of Bolas, Eladamri Korvecdal, Elesh Norn Mother
  of Machines, Flamescroll Celebrant, Food Chain, Gandalf the White,
  Guardian Project, Guardian Sunmare, Kutzil Malamet Exemplar,
  Moon-Blessed Cleric, Sigarda Font of Blessings, Squee the Immortal,
  Sylvan Library, The Jolly Balloon Man, Yasharn Implacable Earth), all
  already subtracted, all closed 2026-08-19. Dozens of distinct shapes
  remain (102 currently), none individually diagnosed. Re-measure and
  diagnose per card rather than batch-guessing.

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
