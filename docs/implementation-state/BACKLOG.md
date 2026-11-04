# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Put a new line in the right document:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history, no residue. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the parser tail. |
| **Singleton queue** | [singletons.md](singletons.md) | One-off cards (confirmed via `parser_probe.py blocked` to share no cluster) — a queue for `hand-author-card`, never batched into a ticket; promote a pair that shares a shape. |
| **Working memory** | [workingOn.md](workingOn.md) | Resumable state of the ticket in progress, incl. a partly done ticket's **residue**. Read first when resuming; delete the block on close. |

**Closing a ticket = deleting it here** and filing its narrative in the matching `Done_*.md`
section — no `[x]`, "shipped" note or "moved to Done" pointer. A partly done ticket keeps only its
terse open point (id, title, one clause) here; residue goes in its `workingOn.md` block. Ticket ids
are stable; reuse a retired id only for the same subject. Sequencing:
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md). Parked tickets and permanent non-goals live in
[DEFERRED.md](DEFERRED.md) (promote by moving the block back here).

| Prefix | Category |
| --- | --- |
| `ENG` | Game engine — turn/stack/priority loop, layers, targeting, combat plumbing |
| `PAR` | Parser — oracle-text → `AbilitySpec` recognition (`parser/oracle/`) |
| `MEC` | Game mechanics — a named MTG mechanic with no engine primitive yet |
| `PLR` | Player management — seats, multiplayer, bots, accounts, sessions |
| `VIS` | Visuals — frontend UI/UX |
| `DB` | Database — card cache, saved decks, persistence, data freshness |
| `ANA` | Deck analysis — UC2 |
| `BUG` | Bugs — a shipped behaviour that is wrong (a wrong-but-`MODELED` claim, a silently dropped clause); not missing coverage |
| `REL` | Release & deployment — steps done when cutting a release (version pins, locks, packaging), not during development |

---

## ENG — Game engine

-No Tickets-

## PAR — Parser

Fragment-axis tickets carry `touched` / `only` counts from a `find-fragments`
discovery: cards containing the family / cards whose every open sentence belongs to
it; overlapping upper bounds, not guaranteed unlocks. Before implementation,
re-scan and verify subfamilies and remaining blockers with `parser_probe blocked`;
before closure, diff full-pool specs for zero losses, execute newly claimed cards,
run the backend suite including full-cache, and re-scan with `find-fragments`.
Latest scan: 2026-11-03, v826, 8,278 open Commander cards / 12,209 fragments.

-No Tickets-

## MEC — Game mechanic

-No Tickets-

## PLR — Player management

- **PLR-9 · User accounts (umbrella).** Split into PLR-9a–e (9a–9d delivered, see `Done_Backend.md`), released in that order; enforcement and
  client updates ship together at the PLR-9e cutover. Design, decisions and verification gates: [plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).
  Asset ownership (PLR-16) and server-route protection (PLR-17) delivered.
- **PLR-9e · Data protection and cutover.** Encryption at rest and backups (decided: SQLCipher for `accounts.db` only, which also holds
  TOTP secrets; other stores rely on an encrypted volume), key handling, security-event logging, `no-store` headers, hide lobby forms in a blocked tab, expire the stale `mtg_client_token` cookie, requirement-to-test mapping, stale user-docs (`01_getting_started.md` "no login", name-based seats in `09_multiplayer.md`),
  coordinated migration/cutover (decided: `migrate_legacy_decks.py` without `--assign-assets-by-name`, no deletion-journal replay), user-docs, docs and Done entries; closes PLR-9.

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width; at 375px the app header (`.app-header-right`) overflows the page and the sidebar must be collapsed by hand.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-5 · Automatic missing-card discovery from saved decks.** After a permitted successful create/import
  or card-list-changing save (metadata-only edits reuse results), enqueue a durable, retryable, coalesced
  job that evaluates every distinct card with the authoritative coverage verdict (`api/saved_decks.py`
  parser version + catalogue signature). Persist deduplicated gap candidates by canonical card identity with
  versioned evidence in a server-data queue under `MTG_DATA_DIR`; keep UNMODELED, permanent Unsupported and
  unresolved card/cache/network errors apart; no source deck id, name, owner or count in the shared queue.
  Runtime stores gap evidence only; classification (singleton vs shared cluster) runs in a developer-side sync
  command that reuses `singleton-sweeper`/`find-fragments` admission rules and merges confirmed singletons
  into `singletons.md` idempotently. Re-evaluate on parser/catalogue/card-pool updates; jobs bind to deck
  version so stale results cannot overwrite newer ones. Show missing cards and status in the UI after saving.
  Needs a job runner (none exists; DYNAMIC_ANALYSIS workers are in-process). Works before PLR-9; under
  accounts it applies to player and admin saves alike. Tests: dedup, restart-survival, stale-job, no provenance
  leak via API/logs, idempotent Markdown sync.

## BUG — Bugs

-No Tickets-

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock (formerly BUG-45b).** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
