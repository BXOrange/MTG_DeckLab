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
| `ANA` | Deck analysis — UC2 (LLM + presentation) |
| `BUG` | Bugs — a shipped behaviour that is wrong (a wrong-but-`MODELED` claim, a silently dropped clause); not missing coverage |

---

## ENG — Game engine


## PAR — Parser

- **PAR-177 · Context-aware gap catalogue and joint-fix ranking.** Fix
  `parser_probe.py rank --by span`; maintain the full-pool phrase/card graph
  with face/block/context identity, explicit opaque blockers and shared
  capabilities across trigger/body roles. Rank prerequisite-aware combinations,
  retaining zero-SOLO groups. Acceptance: A+B/B+C/C+D regression, complete
  unresolved-line accounting, correct modal-wrapper handling and unique-card
  counts for singles, pairs/triples and larger prerequisite packages.

- **PAR-178 · Optional-payment continuations: referents and announced targets.**
  Extend the existing energy-payment/body composition for Aetherstream Leopard,
  Hexgold Slith, Conduit Goblin, Consul's Shieldguard and Eddytrail Hawk.
  Preserve the firing object through the payment choice and announce targeted
  payoffs correctly. Acceptance: pay/decline/insufficient energy, source versus
  selected target, target legality and clone/undo; reuse existing payment effects.

- **PAR-179 · Exiled-source land grants and casting permission.** Compose
  exile-from-hand costs, quoted land mana abilities, “until this card is cast
  from exile” and “for as long as it remains exiled” for Glamorous Outlaw,
  Rakish Revelers, Shattered Seraph, Masked Bandits and Emrakul, the Exigent Doom.
  Preserve independent grant/permission lifetimes and exact card references;
  test casting, other zone exits/re-entry and clone/undo. Spara's Adjudicators
  shares this shape but retains a separate attack/block restriction gap.

- **PAR-180 · Library selection and follow-up composition.** Reuse search/dig
  selections for named-card reveal/hand/shuffle sequences (Avarax, Embermage
  Goblin, Growth-Chamber Guardian) and look/pick/rest sequences (Court Hussar,
  Soulcipher Board, Jar of Eyeballs). Preserve selected-pool references,
  chosen/remaining counts, order and removed-counter X across choices;
  validate the complete sequences and relevant faces, not detached “shuffle”.

- **PAR-181 · Targeted stack-copy grammar and retargeting riders.** Compose
  existing spell/ability-copy effects with “you may choose new targets” for
  Force of Rowan, Adric, Mathematical Genius, League Guildmage and Resonance
  Technician. Preserve spell/ability kinds, controller filters, announced-X
  mana-value bounds and stack identity. Acceptance: legal/illegal originals,
  retained/rechosen targets and paid-X/tapped-artifact counts in actual gameplay.

- **PAR-182 · Attached-host upkeep heads and body references.** Support
  “at the beginning of the upkeep of enchanted creature's controller” with
  attached-creature counter bodies (Unstable Mutation, Essence Flare; catalogue:
  19 shared-head candidates, not 19 guaranteed unlocks).
  Reuse step events and attachment references; test controller changes,
  unrelated players' upkeeps, detached sources and resolving counter effects.
  Size the full shared head family; catalogue matches are candidates, not
  guaranteed complete-card gains.

## MEC — Game mechanic






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

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-2 · Narrative analysis UI** — win conditions, archetype, synergies,
  cohesion score, issues. Sits alongside the existing static/Bracket
  sub-tabs, not replacing them. ANA-1 backend contract is available (see
  [LLM integration](../Reference/LLM_INTEGRATION.md)).
- **ANA-3 · Cache indicator** ("Analysis from X ago") for that LLM result.
  The backend provides `created_at` and `cached`.

## BUG — Bugs
