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
  (2026-08-11, sixth pass): **Ojer 39/77, Rocco 73/98, Glarb Bloomsday
  77/100, staples 173/215, staples 2 398/607, M-K 75/97, Kinnan 78/100**
  (unique-card total 444/719) — re-measure rather than trusting these
  numbers as they age; the per-deck *totals* themselves also drift run to
  run since these are live saved decks a user can keep editing, not a
  frozen fixture. Worklog detail for what's shipped so far — batch by
  batch, why each piece is built the way it is — is in `Done_Backend.md`'s
  "seven 'cEDH'-named saved decks" entries, not here.

  The sixth pass closed every item the fifth pass's own "specific,
  already-diagnosed gaps" list had promoted to next-up (Mox Diamond,
  Mindbreak Trap, Eye of Ugin, Stonehewer Giant/Quest for the Holy Relic,
  Tainted Pact, Transmute Artifact) — no specific per-card gaps left open
  right now; Godo, Bandit Warlord's own second ability is still blocked,
  but on the broader extra-combat-phase gap below, not a search/attach
  shape.

  Broader gaps the fourth pass's full-pool sweep surfaced, each blocking a
  double-digit slice of the remaining residue and needing real design, not
  just a handler: **devotion** (RULE 700.6 — Purphoros/Heliod/Nykthos,
  Shrine to Nyx all need it, nothing today reads a permanent's own pips
  toward it); a general **"players can't `<verb>`"** cross-cutting family
  (search libraries/gain life/draw more than N/untap more than N — Leonin
  Arbiter/Rampaging Ferocidon/Narset-Parter-of-Veils-shaped/Winter Moon/
  Static Orb/Stasis, each needing enforcement wired into the real
  search/life-gain/draw/untap call sites, not a single shared primitive);
  **phasing out an opponent's permanent as a spell effect** + the wider
  "copy a creature except it also `<X>`" family beyond the couple of
  shapes already hand-authored; an **alternative-cost "pitch" family**
  broader than the six Force-of-Will-shaped cards already hand-authored
  (Downhill Charge/Gush/Pyrokinesis/Flare of Denial/Snuff Out/Snapback all
  still print their own alternative cost individually); and RULE 702.26b
  **extra-combat-phase** grants tied to a specific attack condition
  (Combat Celebrant/Godo's "attacks for the first time each turn, untap +
  additional combat" shape, distinct from the already-shipped flat
  "additional combat phase" primitive). None of these should be built
  *for* this ticket alone — each is worth its own ticket once picked up,
  scoped against the wider cache via `parser_probe.py`/`engine_bench.py
  cards`, not just this pool's count.

- **MEC-23 · "Gains all activated abilities of target creature until end
  of turn."** Quicksilver Elemental (Vivi B4 batch, 2026-08-10) — the one
  card left open. MEC-21's batch (2026-08-11) narrowed this: `continuous.
  _apply_borrowed_activated_abilities`/`_retarget_effect_source` now do
  read an arbitrary object's own `activated_abilities` and rebuild each as
  a fresh `ActivatedAbility` redirected onto a different grantee (RULE
  113.7c) — but as a *standing* layer-6 static keyed off `GameObject.
  exiled_with_ids`, not a resolve-time "snapshot a **targeted** creature's
  ability set, for the rest of the turn" grant. What's still genuinely
  open: a resolve-time effect that snapshots `target.activated_abilities`
  at resolution and stamps the rebuilt copies onto the source via a
  turn-scoped field (`temp_*`-shaped, cleared at cleanup like `temp_
  keywords`) rather than the exiled-with static's own live per-pass
  re-derivation. Likely a thin wrapper reusing `_retarget_effect_source`
  rather than a second implementation. Also still needs "you may spend
  blue mana as though it were mana of any color to pay the activation
  costs of ~'s abilities" — MEC-21's `grant_any_color_for_activation` is
  scoped to *creatures you control generally*, not *this one card's own
  granted set specifically*; the same gap Drana and Linvala/Scheming
  Fence's near-identical "any color to activate **those** abilities"
  phrasing needs too (`parser_probe.py cards` — 2 more real cards, found
  while sizing MEC-21, not built there since both also need the
  target-creature/chosen-permanent ability-borrowing half above first).

- **MEC-24 · Single-target "target instant or sorcery card in your
  graveyard gains flashback…" flashback grant.** Vivi B4 batch,
  2026-08-10 — Past in Flames's own untargeted "each…" sibling shipped
  (`grant_graveyard_cast_permission_this_turn`), but the far more common
  *targeted*-singular phrasing (Recoup/Snapcaster Mage/Slickshot
  Lockpicker/Sphinx of Forgotten Lore/Katilda and Lier/The Fugitive
  Doctor — ~10 real cards, `parser_probe.py blocked`) needs a genuinely
  different shape: granting flashback to *one specific, targeted*
  graveyard card rather than broadly to every instant/sorcery there. No
  existing primitive marks a single graveyard object with a temporary
  cast permission the way `exile_with_play_permission`'s `GameState.
  temp_play_permissions` does for an *exiled* card — needs its own
  per-object marker (or reuse of the graveyard-cast permission machinery
  scoped to one `instance_id` instead of "every instant/sorcery you
  control").

## PLR — Player management

- **PLR-4 · Names are the identity, unauthenticated.** Two people picking
  the same name share a seat; the second to connect takes over. Fine for a
  LAN table, not for anything public — needs [PLR-9].
- **PLR-9 · User accounts.** Login/signup (docs/04 PART 4), auth token
  storage + attachment to API/WebSocket calls, browser-refresh reconnect
  flow (docs/04 S1), and login/signup pages. Saved decks are unscoped until
  this exists — anyone hitting the API sees every deck.
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

- **DB-1 · Stale cached rows keep lossy mana-cost data.** A pre-
  `mana_cost_string` row is priced from the legacy pip tally +
  `converted_mana_cost` via `ManaCost.from_card` — correct total/colors, but
  hybrid/Phyrexian nuance is unavailable until the self-healing refetch
  (`Card.has_mana_cost_data`) happens to hit it. `models/mana_cost.py`,
  `services/lazy_card_loader.py`.
- **DB-2 · The commander ban list is hand-maintained.** Scryfall's
  per-printing `legalities` isn't fetched, so there's no live source.
  Deliberately conservative (only long-standing entries that survived unban
  waves); needs manual updates against the official page.
  `services/commander_legality.py`'s `BANNED_COMMANDER_CARDS`.
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
