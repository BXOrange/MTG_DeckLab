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

-No Tickets-

## PAR — Parser

- **PAR-185 · Land animation riders.** Remaining: measured X/X sizes, per-land counter durations and animation group/qualifier variants (residue in `workingOn.md`).
- **PAR-186 · Regeneration riders on destroy.** `destroy that creature/it. it can't be regenerated`, `they can't be regenerated`: 29 + 17 open, 0 sole-blocker; measure the joint package (Dripping Dead, Spinal Graft, Befoul, Crumble, Detonate, …).
- **PAR-187 · Reveal-hand family.** `target opponent/player reveals their hand`, `you choose a nonland card from it`, `that player discards that card`: 53 + 15 open, 0 sole-blocker; the choose-and-act continuation is the missing link (Castigate, Agonizing Remorse, Collective Brutality, Appetite for Brains, …).
- **PAR-188 · Self-power pump amount.** `where x is its power` / `where x is ~'s power`: 12 + 13 open, all 12 sole-blocker (Chameleon Colossus, Dying Wish, Electrostatic Pummeler, Elenda's Hierophant, Faerie Bladecrafter, Feral Animist, Heroes' Bane, Murder Investigation, Spotter Thopter, Tarox Bladewing, Ukkima, Yew Spirit).
- **PAR-189 · Defender and combat-damage riders.** `~ can attack this turn as though it didn't have defender` (12 open, 11 sole-blocker: Mirror Wall, Dark Maze, Glade Watcher, Hightide Hermit, Krotiq Nestguard, …) and `if you do, ~ assigns no combat damage this turn` (12 open, 7 sole-blocker: Laccolith cycle, Ophidian, Dwarven Vigilantes, Farrel's Zealot).
- **PAR-190 · Tribute follow-ups.** `if tribute wasn't paid, …`: 10 open, all sole-blocker (Fanatic of Xenagos, Nessian Demolok, Nessian Wilds Ravager, Oracle of Bones, Ornitharch, Pharagax Giant, Shrike Harpy, Siren of the Fanged Coast, Snake of the Golden Grove, Thunder Brute).
- **PAR-191 · Counter target activated ability.** 5 open, all sole-blocker (Azorius Guildmage, Bind, Rimewind Cryomancer, Squelch, Voidmage Husher); ability-on-stack counter target.
- **PAR-192 · Opening-hand reveal permissions.** `you may reveal this card from your opening hand. if you do, at the beginning of the first upkeep, …`: 8 open (Chancellor cycle, Devourer of Destiny, Providence, Sphinx of Foresight).
- **PAR-193 · Dragon aura return clause.** `when a creature with mana value 6 or greater enters, you may return this card from your graveyard to the battlefield attached to that creature`: 6 open, all sole-blocker (Dragon Breath, Fangs, Scales, Shadow, Wings, Smoke Shroud).
- **PAR-194 · Rune auras.** `as long as enchanted permanent is an equipment, it has "equipped creature has …"`: 5 open, all sole-blocker (Rune of Flight, Might, Mortality, Speed, Sustenance).
- **PAR-195 · Time-counter exile rules.** `whenever a time counter is removed from this card while it's exiled` (6 open, 5 sole-blocker: Aeon Chronicler, Benalish Commander, Detritivore, Dinosaurs on a Spaceship, Fungal Behemoth) and `put a time counter on ~` (9 open).
- **PAR-196 · Depletion and ki counter rules.** `~ doesn't untap during your untap step if it has a depletion counter on it` (Land Cap, Lava Tubes, River Delta, Timberline Ridge, Veldt) and `if there are N or more ki counters on ~, you may flip it` (Budoka Pupil, Callow Jushi, Cunning Bandit, Faithful Squire, Hired Muscle); 10 sole-blocker cards.
- **PAR-197 · Predefined tokens: Lander, Eldrazi Spawn.** `create a Lander token` (11 open, 7 sole-blocker) and the Eldrazi Spawn token with its mana ability (10 open, 6 sole-blocker: Chittering Dispatcher, Eldrazi Repurposer, Emrakul's Messenger, Glaring Fleshraker, Propagator Drone, Skittering Precursor).
- **PAR-198 · "Instead" modifiers.** Kicker/condition `… instead` replacement sentences: 16 open, 14 sole-blocker (Desolation Angel/Giant, Ether Well, Feed the Clan, Fight with Fire, Grizzly Fate, Mysteries of the Deep, Predator's Howl, Ray of Enfeeblement, Ritual of Hope, Take the Fall, We Say Thee Nay!).
- **PAR-199 · Duration-bound exile.** `exile target … until ~ leaves the battlefield`: 10 open, 5 sole-blocker (Annex Sentry, Glass Casket, Grasping Giant, Seam Rip, Solitary Cell); verify what blocks the existing O-ring grammar.
- **PAR-200 · Shuffle graveyard into library.** `target player shuffles their graveyard into their library`: 8 open, all sole-blocker (Blessed Respite, Clear the Mind, Cranial Archive, Learn from the Past, Primal Command, Quest for Ancient Secrets, Reminisce, Thran Foundry).
- **PAR-201 · Opponent gains control of ~.** `target opponent gains control of ~`: 6 open, 5 sole-blocker (Avarice Amulet, Humble Defector, Jinxed Idol, Jinxed Ring, Measure of Wickedness).
- **PAR-202 · End-of-combat trigger head.** `at end of combat` (with intervening-if): 14 open, 5 with other parsed effects (Clockwork cycle, Daredevil Dragster, Dread Wight, Greater Werewolf, Heat Stroke, Kjeldoran Frostbeast, …).
- **PAR-203 · Named choices on resolution.** `choose a creature type` (23 open, 2 sole-blocker), `choose a color` (18), `choose a card name` (17); measure which already-existing choice primitive each lacks.
- **PAR-204 · Optional-payment "if you do" chains.** `you may pay <cost>` (70 open) and `if you do` / `if you don't` (155 / 25 open, 19 / 1 sole-blocker): re-measure after PAR-175/178 and split by antecedent type.

## MEC — Game mechanic

-No Tickets-

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

- **BUG-35 · Ward payment lost on clone/undo.** Clone a game after a normal Ward trigger opens its payment choice, then decline: the targeted spell resolves instead of being countered (RULE 702.21a). `RulesEngine._pending_ward_item`, `_pending_ward_cost` and `_pending_ward_caster_id` are absent from cloned `GameState`; the choice itself survives. Move the resumable Ward payment state into state-owned data and preserve the correct stack item, caster and resolved cost across clone/undo. Validate pay/decline after the prompt and isolation from the original game; reproduction does not require animation.
