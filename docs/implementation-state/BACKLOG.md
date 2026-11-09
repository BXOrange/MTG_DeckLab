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
Latest scan: 2026-11-05, v830, 8,246 open Commander cards / 12,170 fragments.

Body/sentence tickets (PAR-237..242) from the same scan's template ranking (`touched` / `solo`; per-template upper bounds):

- **PAR-237** Modal header behind activation costs (`{1}, sacrifice ~: choose 1 —`, `{1}{g}, {t}: choose 1 —`): 17 touched, 4 solo (Cankerbloom, Goblin Cratermaker, Insidious Fungus, Ransom Note).
- **PAR-240** Conditional ETB tapped: `if you control <n> or more other lands, ~ enters tapped` (5 touched, 4 solo; Cave of the Frost Dragon, Den of the Bugbear, Hall of Storm Giants, Lair of the Hydra).
- **PAR-243** `is dealt excess noncombat damage` trigger heads (RULE 120.4a): Fall of Cair Andros, Magmatic Galleon, Toralf, God of Fury (`x` / "the excess" is that excess). Excess damage exists as an amount (`excess_damage_this_way`), but `DAMAGE` events don't carry it yet. 3 solo.
- **PAR-244** `enchanted planeswalker` Aura clauses (Talent cycle): head `whenever you activate a loyalty ability of enchanted planeswalker` (Elspeth's, Rowan's Talent; Rowan's body copies that ability), body `put a loyalty counter on enchanted planeswalker` (Teferi's, Vivien's Talent), `a creature deals damage to enchanted planeswalker` plus a granted quoted loyalty ability (Liliana's Talent). 5 cards.
- **PAR-245** Per-card `<type> card leaves your / an opponent's graveyard` trigger heads: only the batch `CARDS_LEFT_GRAVEYARD` (`left_graveyard_types`) exists, no per-card exit event. Murktide Regent (also `enters with a +1/+1 counter for each instant and sorcery card exiled with it`), Along the Crooked Way (also a menace-grant activation), Erebos's Titan (also `as long as your opponents control no creatures`). 3 touched, 0 solo: schedule with their second clauses.
- **PAR-248** Mass graveyard exile on entry: `when ~ enters, exile all creature cards from your graveyard` (2 solo: Yggdrasil, Rebirth Engine; Zombie Mob).
- **PAR-249** Token quoted abilities that name the creating card (`named ~`, RULE 201.5): the normalizer folds that name to `~`, which would read as the token's own name. Deathpact Angel, Rekindling Phoenix, Sengir Nosferatu, Sound the Call (4 solo).
- **PAR-251** `target creature or vehicle card` graveyard filter: Back on Track, Broodheart Engine, Fire Nation Salvagers, Imperial Recovery Unit, Okiba Salvage (the last also needs its `then put 2 +1/+1 counters on that permanent if` rider).
- **PAR-252** Prepared state beyond the self form (RULE 722; `become_prepared` covers only `~ becomes prepared`): `target creature becomes prepared` and each-creature forms (Biblioplex Tomekeeper, Codie, Hexhaven Dueling Arena, Skycoach Waypoint), `becomes unprepared` (Biblioplex Tomekeeper, Infinite Coursework), and the intervening-if `if ~ isn't prepared` (Paradox Shaper, Stingerquill Voxmancer, Woodwork Prodigy; also Joined Researchers).
- **PAR-254** `<verb> a creature card from among the cards milled this way` as a referent for a following clause: Airlift Chaplain, Fallaji Archaeologist, Ravenous Gigamole, Shadow Kin, Szarekh the Silent King, Tomakul Scrapsmith, Wasteful Harvest. Verify the shared shape first.

## MEC — Game mechanic

## PLR — Player management

- **PLR-9 · User accounts (umbrella).** Split into PLR-9a–e, released in that order; enforcement and
  client updates ship together at the PLR-9e cutover. Design, decisions and verification gates: [plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).
  Coordinate asset ownership with PLR-16 (hard gate for the cutover) and operator authorization with PLR-17.
- **PLR-9a · Run modes, account storage and authentication.** Default LAN mode accepting only the host's
  own IP ranges (VPN interfaces included), `--online` (HTTPS-only secure mode), `--localdev` (loopback,
  default-localuser that can log out and be replaced by a player login); separate `accounts.db` with
  versioned migrations; password hashing (Argon2id, or stdlib scrypt if no new dependency is wanted —
  decide with measurements); sessions, `/api/auth`, CSRF/Origin extension of `request_guard.py`,
  throttling; unique login and display names; login/signup UI slice; update the `CLAUDE.md`/OPERATIONS startup directive.
- **PLR-9b · Deck and session ownership.** Deck scope (`global`/`private`/`unassigned`) and owner in SQL;
  authorization through every `get_deck` consumer; private Goldfisch/Solo/Replay session ownership;
  operator migration command (bulk "assign to account" mode); needs PLR-9a.
- **PLR-9c · Multiplayer identity and reconnect.** Bind `LobbyPlayer` to accounts, authenticated WS, remove
  name/client-token/secret fallbacks, single-session lock (second tab with the same account is blocked
  with "Blockiert aufgrund paralleler Session"); needs PLR-9a/9b.
- **PLR-9d · Administration.** Separate admin entrypoint (`/api/admin`, dedicated host, MFA before remote
  use): player list/create/disable/delete and session revoke (no admin-initiated password reset), global-deck
  CRUD, allowlisted DB-update jobs, audit log; needs PLR-9a/9b, enforcement of update routes via PLR-17.
- **PLR-9e · Data protection and cutover.** Encryption at rest and backups (decide SQLCipher vs encrypted
  volume first), key handling, security-event logging, `no-store` headers, requirement-to-test mapping,
  coordinated migration/cutover, docs and Done entries; closes PLR-9.
- **PLR-16 · Bind player assets to an owner instead of the free-text name.** Sleeves,
  token art and favorites (`services/player_assets.py`) are keyed by the freely chosen
  name: anyone can upload or delete under any name (`/api/players/{name}/…`). The sweeper
  also deletes a name's uploads when a foreign token expires (`delete_all_for_player(name)`
  in `api/multiplayer_ws.sweep_once`), which lets an attacker who uses the victim's name with
  their own token wipe the victim's art. Tasks: until PLR-9 lands, accept writes/deletes only
  with the lobby secret (`LobbyPlayer.secret`) of the owning player; purge only uploads the expired token created
  itself (store the token/owner per row); after PLR-9a–c, migrate to `account_id`.
- **PLR-17 · Protect admin/server routes.** Anyone who can reach the port can change or clear
  the LLM settings (`PUT /api/llm/settings`), burn LLM quota (`/api/llm/test`, narrative
  analysis, LLM bots) and start the card-pool/combo updates (`/api/cards/update`,
  `/api/combos/update`). Tasks: authorize allowlisted database refresh/update routes
  for authenticated admin accounts only; player accounts must be denied even via
  direct API calls. LLM settings/tests and other server operations remain OS-operator
  only, outside the admin account permission set. Loopback alone does not authorize
  a browser request. Coordinate separate admin identities/UI with PLR-9d; tests.

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.
- **VIS-21 · Hard-coded German picker labels.** `gameBoardView.js` passes literal German labels to the tap-cost
  pickers ('zu tappende Kreatur', 'zu tappende bleibende Karte', ~lines 3222, 3355, 3495), so the English UI
  shows German. Move them into `locales/de|en/board.js` keys and sweep the board for other literal UI text.

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

- **BUG-55 · Extra beginning phase on the first turn skips the draw.** An `additional_beginning_phase` (Cyclonus, Cybertronian Fighter) inserted into the game's very first turn gets no draw step, because the first-turn draw skip (RULE 103.8a) is applied to every draw step of that turn instead of only the turn's first one. Fix the skip so it applies to the first draw step only; test with a converted Cyclonus on turn 1.
- **BUG-56 · "Except it has this ability" is not copiable.** Become-a-copy effects keep the resolving ability as a bound object (`copy_mechanics.this_ability_only`), so it is never part of the copy's copiable values and a Clone copying that permanent does not get it, against RULE 707.9a. Affects Cemetery Puca, Unstable Shapeshifter, The Ever-Changing 'Dane, Likeness Looter, Crystalline Resonance, Aurora Shifter. Reproduce: copy a creature with Unstable Shapeshifter, then enter a Clone copying it and check for the ability.

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock (formerly BUG-45b).** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
