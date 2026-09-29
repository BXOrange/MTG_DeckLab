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

---

## ENG — Game engine

No open tickets.

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not closeable).** Strategy, coverage,
  worked examples and the Commander-legal tail taxonomy (`scripts/commander_tail_report.py`) live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md). Two tracks: **basic mechanics** (generic shapes,
  cache-wide yield — re-run `rank` before trusting "exhausted"; Bucket B still finds clusters) and
  **set-specific mechanics** (a set/precon's signature keyword, worked deck-first). Planechase/
  Archenemy card bodies fold in here (~13/309 done).

  > **Ids:** `PAR-1`…`PAR-131` are taken — grep `Done_Backend.md` before reusing one. First free:
  > **`PAR-134`**; next free `MEC`: **`MEC-105`**. A new engine primitive found along the way files
  > as its own `MEC-*` (`MEC-102` is MEC-101's follow-up).
  >
  > **Anti-proliferation:** a 2-6 card cluster is not automatically a ticket. Bundle independently
  > verified small fixes into one "small verified residue batch" (PAR-92/98 pattern: one id, a
  > sub-bullet per shape); a true one-off goes to [singletons.md](singletons.md). When a close-out
  > surfaces residue, first sweep for an existing ticket, size each shape against the full cache,
  > then batch. A batch stays here until a run starts it; then it gets a `workingOn.md` block.

- **PAR-118 · "Exile a card from your hand with N time counters on it, it gains suspend."** Alaundo
  the Seer, The Eleventh Doctor, The Wedding of River Song (3 SOLO). Suspend is engine-complete
  (`GameObject.granted_suspend`, `remove_suspend_time_counter`, `SuspendUpkeepEffect`); missing is the
  optional hand-to-exile pick stamping `time` counters = mana value + the suspend grant, Wedding's
  "target opponent does the same", and Alaundo's granted `LAST_TIME_COUNTER_REMOVED` trigger + per-owner
  "remove a time counter from each other card" sweep.
- **PAR-132 · Dependent target/body follow-up batch.** Distinct effect-body, trigger-head and
  duration clusters exposed by PAR-130; calibrated clusters live in `PARSER_LONG_TAIL.md`.
- **PAR-133 · Powerstone tokens.** "create a [tapped] Powerstone token" — a `data/tokens.json` entry
  with its RULE 605.3a-restricted mana ability, then `_NAMED_TOKEN_WORDS` (25 solo cards).
- **PAR-129 · A line starting with "Exhaust" is swallowed as a keyword line (wrong-but-MODELED).** 11
  MODELED cards lose an ability: the card-level keyword pass claims the first "Exhaust…" line as the
  bare keyword, so no spec is emitted (Liliana the Repentant, Mai, Jaded Edge, Marshals' Pathcruiser,
  Redshift, Rocketeer Chief/Boostbuggy, Sita Varma, Skyserpent Seeker, Spire Mechcycle, Trackhand
  Trainer; one of three on Audacious Knuckleblade; Boom Scholar loses its static). The lines segment
  correctly alone (`activated` + `activate_only_once_marker`) — the fault is the keyword pass.
- **PAR-128 · Target/group-grammar slots.** Group selectors, the graveyard target grammar, plural
  multi-target scope and filter-before-scope don't take the controller/"another" slots yet.
- **PAR-121 · Subject-scope slot and per-verb connective de-duplication (no coverage change).** A
  third of the regexes sit in near-duplicate clusters: **(a) subject scope** — one verb re-registered
  per subject (prevent-damage ≈27 rows, skip-untap, pump previous/target/group, its-controller
  draw/discard, attached tap/exile/phase-out); **(b) connectives** — the `_X_THEN_WHEN_YOU_DO_RE`
  family re-matches antecedents the clause parser already handles; plus 32 `*_DEVOTION_*` rows (fold
  into `count_phrase`). Maintainability work: do it when touching a verb, never as a large batch
  (audit shipped rows, delete strict subsets).
- **PAR-122 · Trigger doublers.** Player-event causes and compound subjects still fail closed (32
  cached "triggers an additional time" cards; primitive `continuous.trigger_doubler_bonus` exists).
- **PAR-123 · Group-subject pronouns.** A bare "it" under a group trigger isn't read as the firing
  object by every effect type yet.
- **PAR-99 · Khans/Dragons Siege cycle.** The ETB choice parses; unclaimed on all 5 cards (0 SOLO) is
  each mode's standing text — a stored choice gating which of two ongoing abilities is live (Citadel,
  Frontier, Monastery, Outpost, Palace Siege).
- **PAR-100 · "At the beginning of each player's draw step, that player draws an additional card".**
  "That player" binds to the player whose step it is; 10 SOLO + Mornsong Aria (Academy Loremaster,
  Anvil of Bogardan, Dictate of Kruphix, Font of Mythos, Howling Mine, Kami of the Crescent Moon,
  Nekusar, Rites of Flourishing, Spiteful Visions, Teferi's Puzzle Box).
- **PAR-102 · Pump + keyword/quoted-ability grant in one sentence.** "Target creature gets +N/+N and
  gains `<keyword>`/"`<quoted>`" until end of turn" — 104 SOLO, 34 also-blocked (PV 447). **(a) Plain
  keyword tail** (86 SOLO, e.g. Enlarge): widen `catalogue/keywords.py` + the pump row's tail.
  **(b) Quoted tail** (18 SOLO): have the shell recurse into the standard ability grammar (as
  `_QUOTED_GRANT_RE` does for statics); 8 ride "when ~ dies, return it to the battlefield…" (Abnormal
  Endurance, Perigee Beckoner, Return to Action, Supernatural Stamina, Demonic Gifts, Fake Your Own
  Death, Presumed Dead, Ashnod's Intervention), 3 ride "whenever ~ deals combat damage to a player"
  (Dreadmaw's Ire, Hunter's Prowess, Unnatural Moonrise), Viconia ×2 "spend mana as though any color".
  Afterwards route non-parsing inner abilities (Full Steam Ahead, Galuf's Final Act, Greater Stone
  Spirit, Tower Above) to `singletons.md`.
- **PAR-103 · "When `<name>` is put into a graveyard from anywhere, shuffle it into its owner's
  library" (plain trigger).** Not PAR-92's replacement form. 1 SOLO (Worldspine Wurm), 5 also-blocked
  (Dread, Guile, Purity, Serra Avatar, Vigor).
- **PAR-104 · TMNT "create a mutagen token".** 15 SOLO, 2 also-blocked (April O'Neil Human Element,
  Crustacean Commando, Genghis Frog, Michelangelo Weirdness to 11, Mona Lisa, Mutant Chain Reaction,
  Ooze Spill, Ray Fillet Man Ray, …).
- **PAR-105 · "You may cast creature spells from the top of your library".** PAR-88's shape on
  `game/top_library.py`; 5 SOLO, 3 also-blocked (Augur of Autumn, Elven Chorus, Garruk's Horde,
  Ranger Class, Summoning Materia).

> PAR-99…105 counts confirmed at PV 413 (2026-09-16, vs the 56 saved decks in `deck_coverage.py`),
> re-verified at PV 447 (2026-09-21). Re-run `parser_probe.py blocked` before starting.

- **PAR-107 · Small residue batch — graveyard/library/exile.** Clauses (cache-wide count; SOLO = only
  blocker) — work each independently:
  - God-Eternal "dies or exiled → put third from top" — 5 (2 SOLO: Oketra, Ilharg; Bontu/Kefnet/Rhonas
    each blocked by a second clause).
  - "You may cast this card from your graveyard" (plain) — 3 (Hogaak, Skaab Ruinator, Their Number Is Legion).
  - "Counter target spell unless its controller pays `<cost>` for each card in your graveyard" — 3
    (Circular Logic, Countervailing Winds, Rakshasa's Disdain).
  - "`<cost>`: target player exiles a card from their graveyard" — 3 (Merrow Bonegnawer, Relic of
    Progenitus, Scrabbling Claws).
  - "Exile target permanent with mana value `<n>` or greater" — 2 (Despark, Kin-Tree Severance).
  - "When ~ dies, put it on the bottom of its owner's library" — 2 (Fell Horseman, Murderous Rider).
  - "Reveal top `<n>`, may put a creature or land into hand, rest into graveyard" — 2 (Grisly Salvage,
    Scout the Borders).
  - "When ~ dies, you may cast it from your graveyard as an Adventure until end of your next turn" — 2
    (Hildibrand Manderville, Mosswood Dreadknight).
  - "You may cast this card from your graveyard using its Blitz ability" — 2 (Sabin, Tenacious Underdog).
  - "Return all artifact and enchantment cards from your graveyard to the battlefield" — 2
    (Brilliant Restoration, Redress Fate).
  - "Look at top `<n>` of target player's library, put back in any order, may have them shuffle" — 2
    (Natural Selection, Portent).
  - "ETB if kicked, search for a land with a basic land type…" — 2 (Sprouting Goblin + rebalance).
  - "ETB target opponent creature gets -X/-X, X = permanent cards in your graveyard" — 2 (Chupacabra
    Echo, Cloud of Darkness).
  - "ETB mill `<n>`, may return a land card from graveyard to hand" — 2 (Eccentric Farmer, Pothole Mole).
  - **Blink axis (one axis, not three — check which of wrapper / target count-filter / return timing the
    existing `_BLINK_*_RE`, `BlinkEffect`, `ExileEffect(remember)`+`ReturnLinkedExileEffect` rows lack):**
    Flickerwisp/Glimmerpoint Stag (ETB, return at next end step), Angel of Condemnation/Roon (`<cost>`
    activated), Displace/Illusionist's Stratagem ("exile up to `<n>` creatures you control, return them").
  - "Return target creature card from your graveyard with an additional +1/+1 counter" — Prison Break
    (SOLO), A-Graveyard Shift (blocked).
  - "End step, if you didn't play a card from exile this turn, create a tapped Powerstone" — Visions of
    Phyrexia (SOLO), A-Visions (different upkeep clause).
  - "ETB look at top `<n>`, may reveal a creature to hand, rest on bottom" — Growing Rites of Itlimoc
    (SOLO), Foul Emissary (blocked).
  - "Search for an instant or flash card, reveal, hand, shuffle" — 2 (Mystical Teachings, Waterlogged
    Teachings).
- **PAR-108 · Small residue batch — miscellaneous shapes (≥2 cards each).**
  - "Destroy target artifact, enchantment, or creature with flying" — 3 (Airship Crash, Broken Wings,
    Return to the Earth).
  - "~ deals damage equal to the sacrificed creature's power to any target" — 3 (Fling, Kazuul's Fury, Thud).
  - "Whenever enchanted land is tapped for mana, its controller adds an additional `<cost>`" — 2
    (Overgrowth, Wolfwillow Haven).
  - "Counter target spell, activated ability, or triggered ability" — 2 (Disallow, Voidslime); widen
    `CounterSpellEffect`'s target kind.
  - "N or more other creatures with power `<n>` or less enter, draw; once each turn" — Welcoming Vampire
    (SOLO), Enduring Innocence (also needs PAR-111).
  - "~ deals `<n>` damage to each non-Dragon creature" — Breath Weapon (SOLO), Desolation of Smaug.
  - "You may have ~ enter as a copy of a creature you control, except it's a Shapeshifter Rogue" — 2
    (Glasspool Mimic, Visage Bandit).
  - "Target opponent exiles a creature or planeswalker with the greatest mana value" — 2 (Blot Out, End
    of the Hunt).
  - "Upkeep, if you have `<n>` or more life, you win" — 2 (Felidar Sovereign, Test of Endurance).
  - "Upkeep, gain X life, X = cards in hand minus `<n>`" — Ivory Tower (SOLO), The Archimandrite.
  - "As long as you have `<n>` life more than starting, creatures get +`<n>`/+`<n>`" — 2 (Leyline of
    Hope, Righteous Valkyrie).
  - "Counter target spell with mana value X" — 2 (Spell Blast, Spell Burst).
  - "Whenever you tap a creature for mana, add an additional `<cost>`" — 2 (Badgermole Cub, Leyline of
    Abundance).
  - "Look at target player's hand" — 2 (Clairvoyance, Peek).
- **PAR-109 · Small residue batch — static/activated abilities & mana.**
  - "Equipped creature has `<quoted ability>`" is a wrapper over six unrelated inner abilities: trigger
    doubler (**PAR-122**); "conjure a card onto the battlefield tapped and attacking" — Stormforged
    Armor (SOLO), Kari Zev; rest → `singletons.md` Batch 3 (Conformer Shuriken, Lobe Lobber, Shuriken,
    Fishing Pole).
  - "[Basic] lands you control have `<quoted mana ability>`" — 4 (Nexos, Worldknit SOLO; Resonating
    Lute, Sovereign's Realm blocked). A real shell gap (even the unrestricted form is unclaimed) plus
    RULE 605.3a spend restrictions (Nexos, Rosheen, Resonating Lute).
  - "Untap ~ during each other player's untap step" — 4 (Bender's Waterskin, Thousand Moons Infantry
    SOLO; Endbringer, Victory Chimes).
  - "`<cost>`: opponents' permanents lose hexproof and indestructible until EOT" — Shadowspear (SOLO),
    Luxior and Shadowspear, The Fire Nation Drill.
  - "You may activate abilities of creatures you control as though they had haste" — Shang-Chi,
    Thousand-Year Elixir (SOLO); Tyvar.
  - "`<cost>`: target land becomes a `<n>`/`<n>` Elemental with haste until EOT; sorcery speed" — 2
    (Llanowar Loamspeaker + rebalance).
  - "`<cost>`: ~ deals `<n>` damage to each other creature with flying" — 2 (Harbinger of the Hunt,
    Scourge of Kher Ridges).
  - "`<cost>`: Dragons you control get +`<n>`/+`<n>` until EOT" — Lathliss (SOLO), Ran and Shaw.
  - "Equipped creature gets +`<n>`/+`<n>` and is every creature type" — 2 (Amorphous Axe, Runed Stalactite).
- **PAR-110 · Small residue batch — board wipes & mass effects.** Check whether `object_filter`/
  `creature_filter` already reaches these before adding rows.
  - "~ deals X damage to each creature" — 2 (Savage Twister, Starstorm).
  - "Each player exiles creature cards from graveyard, sacrifices all creatures, puts exiled cards onto
    the battlefield" — 2 (Living Death, Living End).
  - "Each player chooses creatures with total power `<n>` or less, sacrifices the rest" — 2 (Destined
    Confrontation, Slaughter the Strong).
  - "Put all creatures on the bottom of their owners' libraries" — 2 (Hallowed Burial, Terminus).
  - "Destroy all creatures; gain `<n>` life for each" — Fumigate (SOLO), Avenge.
  - "Destroy all nonartifact creatures" — 2 (Organic Extinction, Their Name Is Death).
  - "Each opponent sacrifices the creature/planeswalker with greatest mana value" — 2 (Flare of Malice,
    Soul Shatter).
  - "Target player mills half their library, rounded down" — 2 (Cut Your Losses, Traumatize).
- **PAR-111 · Small residue batch — ETB/dies/leaves triggers.**
  - Enduring cycle "when ~ dies, if it was a creature, return it… It's an enchantment" — 5, 2 SOLO
    (Enduring Curiosity, Tenacity); Courage (ETB pump+haste), Friendship (double team + cast anthem),
    Innocence (see PAR-108) each have a second clause.
  - "ETB manifest dread, then attach ~ to that creature" — 4 (Conductive Machete, Cursed Windbreaker,
    Dissection Tools, Killer's Mask).
  - "Whenever an opponent's creature enters, you may have that player lose `<n>` life" — 2 (Blood Seeker,
    Suture Priest).
  - "When ~ exploits a creature, scry `<n>`, then draw" — 2 (Stitched Assistant + rebalance).
  - "ETB attach it to target legendary creature you control" — Mithril Coat (SOLO), Mjölnir.
- **PAR-113 · Small residue batch — combat triggers.**
  - "Whenever ~ deals combat damage to a player, you get that many `<cost>`" — Empyreal Voyager, Peema
    Trailblazer (SOLO); Aurora Shifter.
  - "…to an opponent, it deals that much damage to each other opponent" — 3 SOLO (Amarant Coral, Grenzo's
    Ruffians, Hydra Omnivore).
  - "Whenever ~ enters or attacks, you may put a land from a graveyard onto the battlefield tapped" — 2
    SOLO (Soul of Windgrace + rebalance).
  - "Whenever ~ attacks, add `<cost>`; you don't lose this mana as steps end" — 2 SOLO (Brazen
    Collector, Savage Ventmaw).
  - "Whenever ~ attacks, +`<n>`/+`<n>` for each other attacking Goblin" — Goblin Piledriver (SOLO),
    Goblin Rabblemaster.
- **PAR-114 · Small residue batch — cost reduction & alternative costs.**
  - "This spell costs `<cost>` less, X = greatest power among your creatures" — 4 (Mitotic Ultimus,
    Molten Monstrosity, The Great Henge, The Skullspore Nexus).
  - "Additional cost: discard a card or pay `<cost>`" — 3 (Lightning Axe, Pumpkin Bombardment, Titania).
  - "Additional cost: sacrifice a creature or discard a card" — 2 (Bone Shards, Minion Missile).
  - "During turns other than yours, spells you cast cost `<cost>` less" — 2 (Geyser Drake, Naiad of
    Hidden Coves).

> PAR-107…114 counts come from a one-pass `parse_oracle` + `abstract_clause` scan (PV 413, 2026-09-16,
> vs the 56 saved decks); 107…113 re-measured at PV 447. They were not individually re-diagnosed —
> run `parser_probe.py card` first, since intervening "if" clauses and self- vs target-referents change
> the handler shape. Traps: a `<name>` in "`X` has `<name>`" is a wrapper hiding a quoted inner ability
> (decompose before counting); loyalty costs print a Unicode minus (−).

- **PAR-126 · "A spell or ability an opponent controls causes you to discard `<X>`" — self-subject
  trigger family.** MEC-101 built the primitive (`DISCARD_CARD.cause_controller_id`,
  `requires_opponent_caused_discard`, `triggers_mixin._collect_discarded_triggers`) and hand-authored
  Pure Intentions. 16 SOLO cards remain (`blocked "causes you to discard"`), pure parser work: **(a)** a
  bare self-subject passive "~ is discarded" has no recognition (`_TRIGGER_VERBS` has no passive row,
  the self noun list has no "card"); **(b)** the "a spell or ability an opponent controls causes you to
  discard `<referent>`" wrapper (subject is the causing spell) needs its own dispatch row emitting
  `{"event": "DISCARD_CARD", "condition": {"subject": "self"|"you"}, "requires_opponent_caused_discard":
  True}` (precedent `_DAMAGE_TRIGGER_RE`); **(c)** Pure Intentions' `create_turn_trigger` (RULE 603.7a)
  needs generalizing to a parser row. Library of Leng / Nephalia Academy ("an effect causes you to
  discard") are a broader, non-opponent-scoped condition — not this cluster.

## MEC — Game mechanic

No open tickets.

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

- **VIS-4 · Chat / emotes at the table.**
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9.
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
