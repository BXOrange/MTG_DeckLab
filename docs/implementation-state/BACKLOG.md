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

**Star Trek (TRK + TRC) scan, 2026-11-10:** CR 20261106, PARSER_VERSION 870, 647 unique Oracle cards in the two sets, 436 covered (405 `MODELED` + 31 `AUTHORED`, 67.4 %), 211 open. Every open card is assigned below: ENG/MEC (rules primitives), PAR (shared shapes) or the Star Trek section of [singletons.md](singletons.md). Counts are `touched` upper bounds; re-verify each family with `parser_probe blocked` before starting. Done when all 647 are covered (re-run `scripts/coverage_report.py`) **and** a real-engine cast of every newly covered card passes.

- **ENG-57 · CR 20261106 adoption residue.** (1) 903.5f, Commander games do not use sideboards: Commander seats still load one on every path. **Needs a user decision:** follow the rule, or keep it as a deliberate product extension (`tests/api/test_api_sideboard.py` asserts the current behaviour). (2) 701.27j/712.11b: a permanent spell that enters transformed with an instant or sorcery back face should go to the graveyard.

## PAR — Parser

Fragment-axis tickets carry `touched` / `only` counts from a `find-fragments`
discovery: cards containing the family / cards whose every open sentence belongs to
it; overlapping upper bounds, not guaranteed unlocks. Before implementation,
re-scan and verify subfamilies and remaining blockers with `parser_probe blocked`;
before closure, diff full-pool specs for zero losses, execute newly claimed cards,
run the backend suite including full-cache, and re-scan with `find-fragments`.
Latest scan: 2026-11-05, v830, 8,246 open Commander cards / 12,170 fragments.

Body/sentence tickets (PAR-237..242) from the same scan's template ranking (`touched` / `solo`; per-template upper bounds):

- **PAR-279 · Optional "you may instead" draw replacements.** "If you would draw a card, you may instead choose land or nonland and reveal cards from the top of your library until you reveal a card of the chosen kind ..." (Pavel Chekov, First Posting; Abundance; The Salubrious Philosopher shares the optional shape): an optional replacement that opens a choice mid-replacement (RULE 614.1a, 616.1) plus a reveal-until. The only optional draw replacement today is the special-cased Dredge; `draw_multiplier` (PAR-263) is the non-optional sibling. Size with `parser_probe.py blocked "you may instead"` before starting.
- **PAR-265 · Copy-with-exceptions, token and enter-as-copy tails (follow-up to PAR-253).** Token copies with added menace/changeling/haste, "except it isn't legendary and it's an Illusion Artifact in addition", "copy of this card ... sacrifice it", X targets each copied, kicker-gated "for each creature target opponent controls" copies, and enter-as-copy of a creature card in a graveyard with extra types and menace/counters (Ezri Dax, Voq, Dominion Saboteur). Cards: Blastoneuron, Dominion Infiltration, Fractured Identity, Mirror Universe Intrusion, Reg Barclay, Fidgety Fantasist, Tasha Yar, Out of Time, Dominion Saboteur, Ezri Dax, Newly Joined, Voq, Torchbearer (9).
- **PAR-268 · Cast from a non-hand zone with a rider.** "You may cast this card from exile / your graveyard (it enters with a finality counter)", "once during each of your turns you may cast an artifact [creature] spell from your graveyard/the top of your library", plus Zefram Cochrane's "Spacecraft you control enter with two additional charge counters". Reuse `graveyard_cast.py` and `top_library.py` permissions; finality-counter support needs verifying (Excava's catalogue entry documents a simplification). Cards: Khan, Vengeful Heart, Overflow Submatrix, Storied Veteran, Zefram Cochrane, Warp Pioneer (4).
- **PAR-269 · Communicator equipment: "When you cast this spell, copy it" and communicator counts.** Cast trigger that copies the spell itself, and an equipped creature that has a trigger counting "other creatures you control with a communicator attached to them" (unblockable / draw X and put X lands). Cards: Combadge, Starfleet Communicator (2 touched, 2 only).
- **PAR-270 · Disjunctive creature-type lists.** "Klingons and Warriors you control", "Klingon spells and Warrior spells you cast cost {1} less", "attacking Klingons you control get +1/+1", "other Officers, Artificers, Doctors, Pilots, Scientists, and Spacecraft creatures you control get +2/+2", "klingon and warrior creature cards" (a union of subtypes, not an intersection). Cards: Gagh Slinger, I.K.S. Negh'Var, Imperial Flagship, K't'inga-Class Battle Cruiser, Kirk, Man of Action, Kruge, Genesis Seeker, The Promise of Kahless (6).
- **PAR-271 · "Each player reveals the top card of their library, then draws a card" with a consequence from the reveals.** Damage equal to the greatest mana value among the revealed cards; +1/+1 counter for each nonland card. Cards: Alexander, Ship's Fool, Ambassador K'Ehleyr (2).
- **PAR-272 · Hand peek with exile and owner compensation.** "Look at target opponent's hand. You may choose/exile a nonland card from it. That player draws a card / may play it for as long as it remains exiled, costing {2} more". Cards: Salt Vampire, Zero, Incorporeal Sensate (2).
- **PAR-273 · Temporary control grab with untap, haste and riders.** "Gain control of target creature an opponent controls until end of turn. Untap it. It gains haste/trample ... and 'whenever this deals combat damage to a player, create that many tapped Treasure tokens' / becomes a Warrior in addition / at the beginning of the next combat". Cards: Grilka, Widowed Warrior, Worf, Intelligence Contractor, The Wrath of Khan (3).
- **PAR-274 · Reveal until land cards, put onto the battlefield, rest on the bottom in a random order.** Also with a delayed sacrifice of those lands (Will Riker) and a +1/+1 counter on a commander first (Janice Rand). Cards: U.S.S. Voyager, Lone Wanderer, Will Riker, First in the Field, Janice Rand, Essential Aide (3).
- **PAR-275 · Mill then take a card from among them.** "Mill N cards. You may put a permanent/artifact card from among them into your hand" plus a first-spell-this-game rider (First Contact). Cards: First Contact, Transwarp Hub (2; Temporal Anomaly shares the shape).
- **PAR-276 · Put cards from hand onto the battlefield with riders.** "Draw 3 cards. You may put up to three land cards from your hand onto the battlefield tapped", "put a land card from your hand onto the battlefield; if you do, return a land you control at the beginning of the next end step", "put a creature card from your hand onto the battlefield, it gains haste, then put it on the bottom of your library; when you do, draw a card". Cards: Lt. Arex, Ever-Adapting, Erica Ortegas, Plucky Pilot, U.S.S. Farragut, Bold Explorer (3).
- **PAR-280 · "Any opponent may have you <benefit>" (punisher choice put to each opponent).** Distant Memories ("search your library for a card, exile it, then shuffle. Any opponent may have you put that card into your hand. If no player does, you draw three cards") and Sin Prodder: each opponent in turn order may accept (the Distant Memories ruling, RULE 101.4), so it is the existing `all_players_decline_or` primitive with a free cost, `opponents_only`, and paid effects, plus a referent for the card the search/reveal produced and the accepting player as a damage recipient (Sin Prodder). PAR-278's `_punisher_choice` covers the single-opponent form.


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

- **BUG-69 · Planar deck can contain a joke "Phenome-nom" card (flaky `test_a_planechase_game_starts_with_a_face_up_plane`).** `VariantCardDatabase` sorts planar cards by layout, so the silver-border "That's Enough Slices" (type line "Phenome-nom") can be dealt as the starting plane. The full-cache test then fails at random: it failed once on 2026-11-11 and passed 6 times when rerun alone. Reproduce by seeding `make_engine("planechase")` until that card comes up. Fix: keep only real Plane and Phenomenon type lines out of tournament-legal or black-border printings, or decide that joke cards are deliberately allowed and relax the test.

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock (formerly BUG-45b).** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
