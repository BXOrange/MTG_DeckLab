# Backlog — open work, as tickets

**The single list of open work, backend and frontend.** Replaces the former
per-half `ToDo_Backend.md` / `ToDo_Frontend.md`, which no longer exist.

Four kinds of document, kept strictly apart — put a new line in the right
one:

| Kind | Lives in | Rule |
| --- | --- | --- |
| **Open points** | this file | Only open scope. No history. |
| **Worklogs** | [Done_Backend.md](Done_Backend.md), [Done_Frontend.md](Done_Frontend.md) | Append-only. What shipped and *why it was built that way*. |
| **Examples** | [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md) | Calibration samples + strategy for the indefinite parser tail. |
| **Singleton queue** | [singletons.md](singletons.md) | Genuinely one-off cards confirmed (via `parser_probe.py blocked`) to share no cluster with any other cached card — not a ticket, a queue for the `hand-author-card` skill. Never batch these into a `PAR-*`/`MEC-*` ticket; if a later sweep finds a second card sharing one's shape, promote that pair out into a real ticket instead. |

**Closing a ticket = deleting it from this file** and appending its narrative
to the matching `Done_*.md` section. Never leave a `[x]`, a "shipped" note,
or a "moved to Done" pointer here — this file is read in full, often, so
anything finished that stays costs every future read. If only part of a
ticket is done, keep only the part that isn't.

Ticket ids are stable; reuse a retired id only for the same subject.
Plan-level sequencing lives in
[10_COMPLETION_ROADMAP.md](10_COMPLETION_ROADMAP.md).

**Parked tickets and permanent non-goals live in [DEFERRED.md](DEFERRED.md)**,
not here — low-priority / large-and-unscheduled work, plus the "never to be
built" guardrails (Stickers, Attractions, Vanguard avatars). Keeping them out
of this file is deliberate: `BACKLOG.md` is read in full often, so it holds
only work that's actually up for scheduling. Promote a parked ticket by moving
its block back into the matching section here.

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

## PAR — Parser

- **PAR-12 · The indefinite long tail (methodology pointer, not a closeable
  ticket).** Strategy, coverage, worked examples, and the Commander-legal
  tail-sweep taxonomy (`scripts/commander_tail_report.py`) all live in
  [PARSER_LONG_TAIL.md](PARSER_LONG_TAIL.md), not here — `PAR-31…PAR-53`
  (folded in 2026-09-15) was never really a separate ticket, just this same
  indefinite sweep's Commander-legal-first slice. Parser coverage is a
  standing project goal, not a batch with an end date. Two tracks: **basic
  mechanics** (generic shapes, cache-wide yield — the raw-cache
  `rank`-driven pass was "exhausted" 2026-08-28, but re-entering through
  Bucket B still finds real wins, e.g. PAR-78/PAR-79's 65- and 105-card
  clusters — **re-run the tool before trusting "exhausted"**) and
  **set-specific mechanics** (a set/precon's signature keyword, worked
  deck-first). Planechase/Archenemy plane/scheme card *bodies* fold in here
  too (~13/309 done), not a separate ticket.

  > **Ticket-id note:** `PAR-1` through `PAR-114` are all taken — grep
  > `Done_Backend.md` before reusing one (e.g. `PAR-14` is RULE 603.2's
  > trigger limiter, nothing to do with keywords). `PAR-31…PAR-53` was the
  > long-tail's own reserved block (see `PARSER_LONG_TAIL.md`);
  > `PAR-74…PAR-92` is the 2026-09-15 Commander-legal sweep; `PAR-93…PAR-98`
  > is PAR-79's 2026-09-16 close-out split (its true one-offs went to
  > [singletons.md](singletons.md) instead of a ticket); `PAR-99…PAR-106`
  > and the batch tickets `PAR-107…PAR-114` are the 2026-09-16 **saved-deck
  > coverage sweep** (`backend/scripts/deck_coverage.py` across all 56
  > saved decks, cross-referenced against `commander_tail_report.py` at
  > two cluster thresholds — see each ticket's own citation). `PAR-115…
  > PAR-116` were the 2026-09-16 connective-grammar/slot-grammar pair (14_
  > PARSER_GRAMMAR_DESIGN.md's S4/S5, opened once its S0-S3 prerequisites
  > closed under ENG-34…ENG-37); `PAR-115` closed the same day, landing as
  > one incremental connective (`Done_Backend.md`'s own PAR-62 lesson —
  > "S4 lands in increments, contrary to the ticket's own framing" —
  > applied a second time) rather than the ticket's own "rewrite
  > `parse_effect_body`" framing. `PAR-116` closed after its live audit
  > confirmed that PAR-63 had already removed every concrete cross-module
  > duplication, while `TARGET` is the wrong grammar for statics. `PAR-117`
  > is PAR-115's residue (the referent
  > shapes PAR-115 didn't reach). First free id: **`PAR-118`**. A genuinely
  > new engine primitive found along the way still files as its own
  > `MEC-*` ticket — only the sweep itself stays out of this file.
  >
  > **Anti-proliferation note:** a 2-6 card cluster is not automatically its
  > own ticket. Bundle several independently-verified small fixes into one
  > "small verified residue batch" ticket instead (PAR-92, PAR-98) — a
  > numbered sub-bullet per shape, one `PAR-*` id for the lot — and reserve
  > a standalone ticket for a cluster large enough, or mechanistically
  > distinct enough, to be worth tracking on its own. A true one-off (no
  > sibling anywhere in the cache) isn't a ticket at all — it goes in
  > [singletons.md](singletons.md) for `hand-author-card` instead. When
  > closing a large ticket surfaces a pile of small residue (as PAR-79's
  > own close-out did), triage it the same way before filing: sweep for an
  > existing ticket it already belongs under, size each shape against the
  > full cache, then batch the small ones rather than opening one ticket
  > per shape.

- **PAR-93 · Contraption "crank" trigger recognition (RULE 715).** A whole
  unbuilt sub-mechanic — "whenever you crank this Contraption, `<effect>`"
  (the crank event/action, sprocket/target-number resolution) has zero
  recognition today. Unfinity's Contraptions are tournament-legal (not the
  silver-border non-goal). Confirmed 45 SOLO, 0 also-blocked
  (`parser_probe.py blocked "crank this contraption"`). Accessories to
  Murder, Applied Aeronautics, Top-Secret Tunnel.
- **PAR-94 · `ActivationCost.dynamic_reduction` has zero oracle-text
  recognizer.** The engine primitive ("costs `<cost>` less to activate for
  each `<count_selector>`") is fully ready — built for hand-authored
  cards — but no parser row reaches it; every card printing "this ability
  costs `<cost>` less to activate for each `<X>`" stays UNMODELED
  regardless. Confirmed 37 SOLO, 7 also-blocked
  (`parser_probe.py blocked "this ability costs \{"`). A-Llanowar
  Greenwidow and most of the cluster.
  Separately, **not the same primitive**: A-Sewer Crocodile/Sewer
  Crocodile's own "costs `{3}` less to activate if there are 5 or more mana
  values among cards in your graveyard" is a *conditional flat* discount (a
  binary threshold, not a per-unit count) — `dynamic_reduction` has no field
  for this shape. Same ability on two database rows (an Alchemy rebalance +
  the original), so effectively one real card; decide whether a flat-if-
  condition case is worth a shared field or its own small one when this
  lands.
- **PAR-95 · RULE 702.140 Adamant.** Completely unbuilt (`grep -ri adamant`
  finds nothing) — "if at least 3 `<color>` mana was spent to cast this
  spell, `<effect>`" needs *per-colour* spent-mana tracking; today's
  `SPELL_CAST` event only carries the total `mana_spent` (built for
  PAR-79's sixth increment's `spell_mana_spent_at_least`, see
  `Done_Backend.md`). Confirmed 14 SOLO, 3 also-blocked
  (`parser_probe.py blocked "if at least [0-9]+ [a-z]+ mana was spent to
  cast this spell"`). Ardenvale/Embereth/Garenbrig/Locthwain Paladin,
  Foreboding Fruit, Outmuscle, Searing Barrage, Silverflame Ritual, Slaying
  Fire, Sundering Stroke, Turn into a Pumpkin.
- **PAR-96 · "N or more mana was spent to cast that spell" trigger-body
  upgrade.** Distinct from Adamant above (total spent mana, not
  per-colour) — the engine predicate already exists
  (`spell_mana_spent_at_least`, PAR-79's sixth increment) but needs a
  reusable "if `<condition>`, `<effect>` instead/also" intervening-if peel
  on a *trigger* body; today this shape only exists as one-off whole-line
  regexes per exact combination (`_COUNTER_FREE_SPELL_RE`). Confirmed 11
  SOLO, 0 also-blocked (`parser_probe.py blocked "if [0-9]+ or more mana
  was spent to cast that spell"`). Colorstorm Stallion, Deluge Virtuoso,
  Elemental Mascot, Exhibition Tidecaller, Expressive Firedancer,
  Molten-Core Maestro, Phoenix of Iteration, Spectacular Skywhale, Tackle
  Artist, Tellah Great Sage, Thunderdrum Soloist.
- **PAR-97 · Graveyard-batch mill trigger (RULE 603.3f).** "Whenever 1 or
  more [`<type>`] cards are put into your graveyard from your library" as a
  single batch event, distinct from `EventType.MILL_CARD`'s existing
  per-card firing — modeling it naively off the per-card event over-fires
  (RULE 603.3f wants exactly one trigger per simultaneous batch, the same
  reasoning MEC-78's `graveyard_exit_batch()`/`CARDS_LEFT_GRAVEYARD`
  already established; this is that event's mirror-image mill-side sibling,
  which doesn't exist yet). Confirmed 8 SOLO, 4 also-blocked
  (`parser_probe.py blocked "put into your graveyard from your library"`).
  Colossal Grave-Reaver, Creeping Chill, Devourer of Memory, Hedge
  Shredder, Narcomoeba, Pedantic Learning, Polluted Cistern // Dim
  Oubliette, Sidisi, Brood Tyrant.
- **PAR-98 · Small verified residue batch #2.** Fourteen independent,
  already-confirmed small fixes surfaced while closing out PAR-79's own
  "can't be blocked this turn" residue — bundled as one batch rather than
  fourteen tickets, same convention as PAR-92:
  - "Activate only/costs `<cost>` less if you control a legendary
    creature" as an activation restriction/cost-reduction condition — 4
    SOLO (Brotherhood Spy, Esquire of the King, Haunt of the Dead Marshes,
    Rivendell).
  - "Becomes a `<N>`/`<M>` creature. It's still a land." manland-animate
    compound with no explicit colour word, a leading "until end of turn"
    word order, and (on one card) a separate-sentence unblockable tail —
    PAR-79's sixth increment's colour/subtype widening already closed
    every same-template card; this is separately-shaped residue — 3 SOLO,
    1 also-blocked (Creeping Tar Pit, Siege of Towers, Woodwraith
    Corrupter; Frostwalk Bastion also-blocked on an unrelated clause).
  - "Whenever you cast a spell that's both `<color>` and `<color>`" — a
    two-colour AND cast-trigger filter; `_CAST_SPELL_TRIGGER_RE`'s
    `types`/`cast_of_color` slots are single-colour only today — 5 SOLO, 1
    also-blocked (Battlegate Mimic, Nightsky Mimic, Riverfall Mimic).
  - Delayed sac/destroy tail-form dispatch reaching an *activated* (not
    triggered) ability preceded by its own unblockable-grant sentence, plus
    a "destroy it **and** `<self>`" two-object compound
    `_DELAYED_SAC_EXILE_TAIL_RE` has no shape for yet — 2 SOLO (Wings of
    Hubris, Goblin Sappers).
  - Alora, Cheerful Scout/Thief's own "if you do" tail names the returned
    creature ("it") a second time, or opens a *fresh* untargeted
    opponent-choice pick — the eighth PAR-79 increment's `previous_or_self`
    capture deliberately doesn't reach a second pronoun reference inside
    the follow-up (see `Done_Backend.md`'s PAR-79 entry) — 2 SOLO (Alora,
    Cheerful Scout; Alora, Cheerful Thief).
  - A targeted "return `<creature>` to its owner's hand. If you do,
    `<effect measuring the returned creature>`." composition — the
    untargeted `previous_or_self`/`ChooseObjectsEffect` baking mechanism
    doesn't apply to a genuine RULE 115 target (gone from the battlefield
    by the time "if you do" would read it) — 2 SOLO (Niambi, Esteemed
    Speaker; Meanders Guide — untargeted antecedent, targeted follow-up,
    needs the identical composition from the other direction). First
    Responder is a *related but distinct* third shape ("**then**", not "if
    you do", plus a magnitude reading the just-returned creature's power)
    confirmed a true singleton — see `singletons.md`.
  - "Another target `<qualifier>` permanent you control" where the
    qualifier is "historic" or "nonland" — `resolve_target_kind` doesn't
    recognize either combined with "another…you control" at all — 2 SOLO
    (Guardians of Koilos, Stockpiling Celebrant).
  - "Except by creatures with haste" as an evasion-exception filter, paired
    with a haste-granting effect — 3 SOLO (Agility Bobblehead, Run for Your
    Life, Speed, Young Avenger).
  - "Whenever you sacrifice a clue[ or food]" trigger condition — entirely
    unrecognized today — 6 SOLO (Astrid Peth, Blu, Mansion Prince, Jenny
    Flint, Lazav, Wearer of Faces, Martha Jones, +1 more).
  - "If a land card was milled this way" as a conditional gate after a
    "mill a card" clause — 4 SOLO (Loafing Giant, Locke, Treasure Hunter,
    Lorehold Excavation, Saprazzan Breaker).
  - "Except by `<same-color>` creatures" / "except by walls" as a
    static/resolve-time evasion-exception filter (colour- or type-scoped
    permitted-blocker set) — 2 SOLO (Dread Charge, Varchild's Crusader).
  - "When the last time counter is removed from this card[, while it's
    exiled]" trigger condition — unrecognized regardless of body — 3 SOLO
    (Alaundo the Seer, Riftmarked Knight, Veiling Oddity).
  - "Whenever a creature you control explores" trigger condition —
    unrecognized regardless of body — 5 SOLO (Lurking Chupacabra, Merfolk
    Cave-Diver, Nicanzil, Current Conductor, +2 more).
  - "At the beginning of combat on your turn, if you've cast a noncreature
    spell this turn" combat-phase trigger condition — 6 SOLO, 6
    also-blocked (Franklin Richards, Ascendant; H.E.R.B.I.E., Lovable
    Robot; Hurkyl, Master Wizard; Lockjaw, Slobbering Teleporter, +2 more).
  - A cost-`{X}`-driven "power `<N>` or less" target filter/count on an
    unblockable ability — the filter threshold itself reading the
    activation's own paid X (Minamo Sightbender), or an X-sized target
    count paired with a fixed power filter (Runed Arch) — 2 SOLO, related
    but not identical shapes; may or may not share one fix.

  > PAR-93…PAR-98's counts (above) are confirmed via `parser_probe.py
  > blocked` at PARSER_VERSION 412, 2026-09-16 — a full batch newer than
  > PAR-80…PAR-92's own 386 checkpoint. Re-run before starting either
  > batch, same standing rule as every other ranked count in this file.

- **PAR-99 · Khans-of-Tarkir "choose khans or dragons" Siege cycle.** The
  ETB choice itself (`as ~ enters, choose khans or dragons.`) already
  parses — confirmed via `parser_probe.py blocked "as .* enters, choose
  khans or dragons"`: **0 SOLO, 5 also-blocked**. What's unclaimed on all
  5 cards is each mode's own standing consequence text ("khans — at the
  beginning of each of your main phases, add {G}{G}."/"dragons — whenever
  a creature you control with flying enters, you may have it fight target
  creature you don't control.", different per card) — a stored ETB choice
  gating which of two ongoing triggered/static abilities is live for the
  rest of the game, RULE 613.6-adjacent but keyed to a player choice
  rather than a permanent-count threshold. Citadel Siege, Frontier Siege,
  Monastery Siege, Outpost Siege, Palace Siege.
- **PAR-100 · "At the beginning of each player's draw step, that player
  draws an additional card" (+ variants).** An "each player"-scoped draw
  trigger whose effect binds to "that player" (the one whose draw step it
  is) rather than "you" — distinct from the already-shipped "you" forms.
  Confirmed via `parser_probe.py blocked "at the beginning of each
  player.s draw step"`: **10 SOLO, 1 also-blocked**. Academy Loremaster,
  Anvil of Bogardan, Dictate of Kruphix, Font of Mythos, Howling Mine,
  Kami of the Crescent Moon, Nekusar the Mindrazer, Rites of Flourishing,
  Spiteful Visions.
- **PAR-101 · CDA "power (and toughness) is equal to the number of `<X>`"
  family.** A characteristic-defining-ability (RULE 604.3) reading a flat
  board/graveyard count into base power (optionally toughness too) —
  distinct from the already-shipped "+1/+1 for each" anthem-style CDAs.
  Check first whether `continuous.py`'s existing `count_selector` machinery
  (built for PAR-72's Party) reaches this directly, making it pure parser
  recognition. Four related shapes, confirmed via `parser_probe.py
  blocked`: "power is equal to the number of artifacts you control" (**4
  SOLO, 1 also-blocked** — Bronze Guardian, Brotherhood Vertibird,
  Cephalopod Sentry, Filigree Attendant); "power is equal to the number of
  instant and sorcery cards in your graveyard" (**3 SOLO, 2 also-blocked**
  — Enigma Drake, Haughty Djinn, Spellheart Chimera); "power and toughness
  are each equal to the number of artifacts you control" (Master of
  Etherium and siblings); "power is equal to the greatest mana value among
  creatures you control" (Dodgy Jalopy and a sibling); "power is equal to
  the number of land cards in your graveyard" (Uurg, Spawn of Turg and its
  Alchemy rebalance).
- **PAR-102 · Pump + arbitrary keyword/quoted-ability grant in one
  sentence (general form).** "Target/that creature gets +N/+N and gains
  `<keyword>`/"`<quoted ability>`" until end of turn" — PAR-79's own
  widening only covers this combined with *unblockable* specifically;
  every other keyword or quoted-ability tail on the same pump sentence
  stays unrecognized. The single biggest new cluster in this sweep.
  Confirmed via `parser_probe.py blocked "gets \+\[0-9\]/\+\[0-9\] and
  gains"`: **105 SOLO, 34 also-blocked** — re-run and narrow the regex
  before starting, since this spans two sub-shapes that may want separate
  handlers (a plain printed keyword vs. a fully quoted granted ability,
  e.g. Abnormal Endurance's `gains "when ~ dies, return it to the
  battlefield tapped under its owner's control."`). Abnormal Endurance,
  Ashnod's Intervention, Demonic Gifts, Fake Your Own Death, Galuf's Final
  Act, Supernatural Stamina.
- **PAR-103 · "When `<name>` is put into a graveyard from anywhere,
  shuffle it into its owner's library" (plain triggered form).** Distinct
  from PAR-92's already-scoped replacement-effect form ("if `<name>` would
  be put into a graveyard..., reveal `<name>` and shuffle it... instead");
  this is an ordinary RULE 603 trigger with no replacement/reveal. Confirmed
  via `parser_probe.py blocked "is put into a graveyard from anywhere,
  shuffle it into its owner.s library"`: **1 SOLO (Worldspine Wurm), 5
  also-blocked** (Dread, Guile, Purity, Serra Avatar, Vigor — each also
  carries one unrelated second clause of its own).
- **PAR-104 · Teenage Mutant Ninja Turtles "create a mutagen token" set
  mechanic.** A TMNT-specific token type + its ETB/cast-trigger family,
  zero recognition today. Confirmed via `parser_probe.py blocked "create a
  mutagen token"`: **15 SOLO, 2 also-blocked**. April O'Neil Human
  Element, Crustacean Commando, Genghis Frog, Michelangelo Weirdness to
  11, Mona Lisa Ever Adaptable, Mutant Chain Reaction, Ooze Spill, Ray
  Fillet Man Ray.
- **PAR-105 · "You may cast creature spells from the top of your library"
  static permission.** Same shape as PAR-88 (graveyard-zone play
  permission, itself modeled on `game/top_library.py`'s existing
  from-hand-equivalent permission) but for casting creatures specifically
  off the library top — likely a small widening of the same primitive
  rather than a new one. Confirmed via `parser_probe.py blocked "you may
  cast creature spells from the top of your library"`: **5 SOLO, 3
  also-blocked**. Augur of Autumn, Elven Chorus, Garruk's Horde, Ranger
  Class, Summoning Materia.
> **PAR-99…PAR-105's counts are confirmed via `parser_probe.py blocked` at
> PARSER_VERSION 413, 2026-09-16, cross-referenced against the 56 saved
> decks in `backend/scripts/deck_coverage.py`. Re-run before starting —
> same standing rule as every other ranked count in this file.**

- **PAR-107 · Small residue batch — graveyard/library/exile
  interactions.** 26 independently-shaped clauses (each ≥2 cards
  cache-wide, confirmed via `commander_tail_report.py --min-cluster 2`
  cross-referenced against the 56 saved decks) sharing only a broad theme,
  bundled as one ticket rather than 26 — same convention as PAR-92/PAR-98.
  Work each sub-item independently; a template's own card count is cited
  cache-wide, not deck-only:
  - "When `<name>` is put into a graveyard from anywhere, shuffle it into
    its owner's library." — 6 cache-wide (Dread, Guile, Purity, Serra
    Avatar) — **see PAR-103, already split out.**
  - "You may cast creature spells from the top of your library." — 6
    cache-wide — **see PAR-105, already split out.**
  - "When `<name>` dies or is put into exile from the battlefield, you may
    put it into its owner's library third from the top." (the
    God-Eternal cycle) — 5 cache-wide (God-Eternal Bontu, God-Eternal
    Kefnet, God-Eternal Oketra, God-Eternal Rhonas).
  - CDA "power is equal to the number of instant and sorcery cards in your
    graveyard" — 5 cache-wide — **see PAR-101, already split out.**
  - "You may cast this card from your graveyard." (plain, no named
    keyword ability) — 3 cache-wide (Hogaak Arisen Necropolis, Skaab
    Ruinator, Their Number Is Legion).
  - "Counter target spell unless its controller pays `<cost>` for each
    card in your graveyard." — 3 cache-wide (Circular Logic,
    Countervailing Winds, Rakshasa's Disdain).
  - "`<cost>`: target player exiles a card from their graveyard." — 3
    cache-wide (Merrow Bonegnawer, Relic of Progenitus, Scrabbling
    Claws).
  - "When `<name>` enters, if an opponent controls more lands than you,
    search your library for a basic Plains card, put it onto the
    battlefield tapped, then shuffle." — 2 cache-wide (Loyal Warhound,
    Scouting Hawk).
  - "Exile target permanent with mana value `<n>` or greater." — 2
    cache-wide (Despark, Kin-Tree Severance).
  - "When `<name>` dies, put it on the bottom of its owner's library." —
    2 cache-wide (Fell Horseman // Deathly Ride, Murderous Rider // Swift
    End).
  - "Reveal the top `<n>` cards of your library. You may put a creature or
    land card from among them into your hand. Put the rest into your
    graveyard." — 2 cache-wide (Grisly Salvage, Scout the Borders).
  - "When `<name>` dies, you may cast it from your graveyard as an
    Adventure until the end of your next turn." — 2 cache-wide (Hildibrand
    Manderville // Gentleman's Rise, Mosswood Dreadknight // Dread
    Whispers).
  - "You may cast this card from your graveyard using its Blitz ability."
    — 2 cache-wide (Sabin Master Monk, Tenacious Underdog).
  - "Return all artifact and enchantment cards from your graveyard to the
    battlefield." — 2 cache-wide (Brilliant Restoration, Redress Fate).
  - "Look at the top `<n>` cards of target player's library, then put them
    back in any order. You may have that player shuffle." — 2 cache-wide
    (Natural Selection, Portent).
  - "When `<name>` enters, if it was kicked, search your library for a
    land card with a basic land type, reveal it, put it into your hand,
    then shuffle." — 2 cache-wide (Sprouting Goblin + its Alchemy
    rebalance).
  - "`<name>`'s power is equal to the number of land cards in your
    graveyard." — 2 cache-wide (Uurg, Spawn of Turg + its Alchemy
    rebalance) — **see PAR-101, already split out.**
  - "When `<name>` enters, target creature an opponent controls gets
    -X/-X until end of turn, where X is the number of permanent cards in
    your graveyard." — 2 cache-wide (Chupacabra Echo, Cloud of Darkness).
  - "When `<name>` enters, mill `<n>` cards, then you may return a land
    card from your graveyard to your hand." — 2 cache-wide (Eccentric
    Farmer, Pothole Mole).
  - "When `<name>` enters, exile another target permanent. Return that
    card to the battlefield under its owner's control at the beginning of
    the next end step." — 2 cache-wide (Flickerwisp, Glimmerpoint Stag).
  - "Return target creature card from your graveyard to the battlefield
    with an additional +1/+1 counter on it." — 2 cache-wide (Prison
    Break + its Alchemy rebalance).
  - "`<cost>`, `<cost>`: exile another target creature. Return that card
    to the battlefield under its owner's control at the beginning of the
    next end step." — 2 cache-wide (Angel of Condemnation, Roon of the
    Hidden Realm).
  - "At the beginning of your end step, if you didn't play a card from
    exile this turn, create a tapped Powerstone token." — 2 cache-wide
    (Visions of Phyrexia + its Alchemy rebalance).
  - "When `<name>` enters, look at the top `<n>` cards of your library.
    You may reveal a creature card from among them and put it into your
    hand. Put the rest on the bottom of your library in any order." — 2
    cache-wide (Foul Emissary, Growing Rites of Itlimoc // Itlimoc,
    Cradle of the Sun).
  - "Exile up to `<n>` target creatures you control, then return those
    cards to the battlefield under their owner's control." — 2 cache-wide
    (Displace, Illusionist's Stratagem).
  - "Search your library for an instant card or a card with flash, reveal
    it, put it into your hand, then shuffle." — 2 cache-wide (Mystical
    Teachings, Waterlogged Teachings // Inundated Archive).
- **PAR-108 · Small residue batch — miscellaneous shapes.** 14
  independently-shaped clauses (excluding the 3 already split out into
  their own tickets above), each ≥2 cards cache-wide:
  - "Destroy target artifact, enchantment, or creature with flying." — 3
    cache-wide (Airship Crash, Broken Wings, Return to the Earth) — a
    three-way OR across different characteristic dimensions: two card
    types plus one keyword-bearing creature filter.
  - "`<name>` deals damage equal to the sacrificed creature's power to any
    target." — 3 cache-wide (Fling, Kazuul's Fury // Kazuul's Cliffs,
    Thud).
  - "Whenever enchanted land is tapped for mana, its controller adds an
    additional `<cost>`." — 2 cache-wide (Overgrowth, Wolfwillow Haven).
  - "Counter target spell, activated ability, or triggered ability." — 2
    cache-wide (Disallow, Voidslime) — generalize `CounterSpellEffect`'s
    target kind beyond "spell" to abilities on the stack.
  - "Whenever N or more other creatures you control with power `<n>` or
    less enter, draw a card. This ability triggers only once each turn."
    — 2 cache-wide (Enduring Innocence, Welcoming Vampire).
  - "`<name>` deals `<n>` damage to each non-Dragon creature." — 2
    cache-wide (Breath Weapon, Desolation of Smaug).
  - "You may have `<name>` enter as a copy of a creature you control,
    except it's a Shapeshifter Rogue in addition to its other types." — 2
    cache-wide (Glasspool Mimic // Glasspool Shore, Visage Bandit).
  - "Target opponent exiles a creature or planeswalker they control with
    the greatest mana value among creatures and planeswalkers they
    control." — 2 cache-wide (Blot Out, End of the Hunt).
  - "At the beginning of your upkeep, if you have `<n>` or more life, you
    win the game." — 2 cache-wide (Felidar Sovereign, Test of Endurance).
  - "At the beginning of your upkeep, you gain X life, where X is the
    number of cards in your hand minus `<n>`." — 2 cache-wide (Ivory
    Tower, The Archimandrite).
  - "As long as you have at least `<n>` life more than your starting life
    total, creatures you control get +`<n>`/+`<n>`." — 2 cache-wide
    (Leyline of Hope, Righteous Valkyrie).
  - "Counter target spell with mana value X." — 2 cache-wide (Spell
    Blast, Spell Burst).
  - "Whenever you tap a creature for mana, add an additional `<cost>`." —
    2 cache-wide (Badgermole Cub, Leyline of Abundance).
  - "Whenever you cast a spell from anywhere other than your hand, draw a
    card." — 2 cache-wide (Vega the Watcher + its Alchemy rebalance).
  - "Look at target player's hand." — 2 cache-wide (Clairvoyance, Peek).
- **PAR-109 · Small residue batch — static/activated abilities &
  mana.** 9 independently-shaped clauses, each ≥2 cards cache-wide:
  - "Equipped creature has `<name>`" (a quoted/named granted ability via
    Equipment specifically) — 6 cache-wide (Conformer Shuriken, Fishing
    Pole, Lobe Lobber, Shuriken).
  - "Untap `<name>` during each other player's untap step." — 4
    cache-wide (Bender's Waterskin, Endbringer, Thousand Moons Infantry,
    Victory Chimes).
  - "`<cost>`: permanents your opponents control lose hexproof and
    indestructible until end of turn." — 3 cache-wide (Luxior and
    Shadowspear, Shadowspear, The Fire Nation Drill).
  - "You may activate abilities of creatures you control as though those
    creatures had haste." — 3 cache-wide (Shang-Chi Master of Kung Fu,
    Thousand-Year Elixir, Tyvar Jubilant Brawler).
  - "`<cost>`: target land you control becomes a `<n>`/`<n>` Elemental
    creature with haste until end of turn. It's still a land. Activate
    only as a sorcery." — 2 cache-wide (Llanowar Loamspeaker + its
    Alchemy rebalance).
  - "`<cost>`: `<name>` deals `<n>` damage to each other creature with
    flying." — 2 cache-wide (Harbinger of the Hunt, Scourge of Kher
    Ridges).
  - "`<cost>`: Dragons you control get +`<n>`/+`<n>` until end of turn."
    — 2 cache-wide (Lathliss Dragon Queen, Ran and Shaw).
  - "`<cost>`, `<cost>`: untap another target artifact." — 2 cache-wide
    (Manifold Key, Sonic Screwdriver).
  - "Basic lands you control have `<name>`" — 2 cache-wide (Nexos,
    Sovereign's Realm).
  - "Equipped creature gets +`<n>`/+`<n>` and is every creature type." —
    2 cache-wide (Amorphous Axe, Runed Stalactite).
- **PAR-110 · Small residue batch — board wipes & mass effects.** 10
  independently-shaped clauses, each ≥2 cards cache-wide:
  - "This spell costs `<cost>` less to cast for each creature that
    attacked this turn." — 3 cache-wide (Rowdy Research, The Mary Janes,
    Witchstalker Frenzy).
  - "This spell costs `<cost>` less to cast for each creature that died
    this turn." — 3 cache-wide (Blood for the Blood God!, Death-Rattle
    Oni, Diregraf Rebirth).
  - "`<name>` deals X damage to each creature." — 2 cache-wide (Savage
    Twister, Starstorm).
  - "Each player exiles all creature cards from their graveyard, then
    sacrifices all creatures they control, then puts all cards they
    exiled this way onto the battlefield." — 2 cache-wide (Living Death,
    Living End).
  - "Each player chooses any number of creatures they control with total
    power `<n>` or less, then sacrifices all other creatures they
    control." — 2 cache-wide (Destined Confrontation, Slaughter the
    Strong).
  - "Put all creatures on the bottom of their owners' libraries." — 2
    cache-wide (Hallowed Burial, Terminus).
  - "Destroy all creatures. You gain `<n>` life for each creature
    destroyed this way." — 2 cache-wide (Avenge, Fumigate).
  - "Destroy all nonartifact creatures." — 2 cache-wide (Organic
    Extinction, Their Name Is Death).
  - "This spell costs `<cost>` less to cast for each creature your
    opponents control." — 2 cache-wide (Primeval Protector, Wall Off).
  - "Each opponent sacrifices a creature or planeswalker with the
    greatest mana value among creatures and planeswalkers they control."
    — 2 cache-wide (Flare of Malice, Soul Shatter).
  - "Target player mills half their library, rounded down." — 2
    cache-wide (Cut Your Losses, Traumatize).
- **PAR-111 · Small residue batch — ETB/dies/leaves-the-battlefield
  triggers.** 6 independently-shaped clauses (excluding PAR-104, already
  split out), each ≥2 cards cache-wide:
  - "When `<name>` dies, if it was a creature, return it to the
    battlefield under its owner's control. It's an enchantment." (the
    Enduring cycle) — 5 cache-wide (Enduring Courage, Enduring Curiosity,
    Enduring Friendship, Enduring Innocence).
  - "When `<name>` enters, manifest dread, then attach `<name>` to that
    creature." — 4 cache-wide (Conductive Machete, Cursed Windbreaker,
    Dissection Tools, Killer's Mask).
  - "Whenever a creature an opponent controls enters, you may have that
    player lose `<n>` life." — 2 cache-wide (Blood Seeker, Suture
    Priest).
  - "Whenever a creature an opponent controls dies, that player loses
    `<n>` life." — 2 cache-wide (Assault Intercessor, Massacre Wurm).
  - "When `<name>` exploits a creature, scry `<n>`, then draw a card." —
    2 cache-wide (Stitched Assistant + its Alchemy rebalance).
  - "When `<name>` enters, destroy target artifact or enchantment an
    opponent controls." — 2 cache-wide (Rambunctious Mutt, Witch
    Enchanter // Witch-Blessed Meadow).
  - "When `<name>` enters, attach it to target legendary creature you
    control." — 2 cache-wide (Mithril Coat, Mjölnir Storm Hammer).
- **PAR-112 · Small residue batch — counters, tokens & CDA formulas.** 5
  independently-shaped clauses (excluding PAR-101's own sub-items, already
  split out), each ≥2 cards cache-wide:
  - "Create X `<n>`/`<n>` white Angel creature tokens with flying." — 2
    cache-wide (Decree of Justice, Entreat the Angels).
  - "−`<n>`: target opponent gets an emblem with `<name>`" — 2 cache-wide
    (Garruk Apex Predator, Ob Nixilis Reignited).
  - "Whenever you sacrifice a permanent, put a +`<n>`/+`<n>` counter on
    `<name>`." — 2 cache-wide (Blood Aspirant, Juri Master of the
    Revue).
  - "At the beginning of your end step, if you gained life this turn,
    create a `<n>`/`<n>` white Cat creature token. Then if you have the
    city's blessing, for each token you control that entered this turn,
    create a token that's a copy of it." — 2 cache-wide (Ocelot Pride +
    its Alchemy rebalance).
- **PAR-113 · Small residue batch — combat triggers.** 6
  independently-shaped clauses, each ≥2 cards cache-wide:
  - "Whenever `<name>` deals combat damage to a player, you get that many
    `<cost>`." — 3 cache-wide (Aurora Shifter, Empyreal Voyager, Peema
    Trailblazer).
  - "Whenever a creature you control with power `<n>` or greater enters,
    draw a card." — 3 cache-wide (Elemental Bond, Garruk Curse Breaker,
    Kiora Behemoth Beckoner).
  - "Whenever `<name>` deals combat damage to an opponent, it deals that
    much damage to each other opponent." — 3 cache-wide (Amarant Coral,
    Grenzo's Ruffians, Hydra Omnivore).
  - "Whenever `<name>` enters or attacks, you may put a land card from a
    graveyard onto the battlefield tapped under your control." — 2
    cache-wide (Soul of Windgrace + its Alchemy rebalance).
  - "Whenever `<name>` attacks, add `<cost>`. Until end of turn, you
    don't lose this mana as steps and phases end." — 2 cache-wide
    (Brazen Collector, Savage Ventmaw).
  - "Whenever `<name>` attacks while you control a creature with power
    `<n>` or greater, `<name>` gets +`<n>`/+`<n>` until end of turn." — 2
    cache-wide (Nighthowl Pursuer, Ruby Daring Tracker).
  - "Whenever `<name>` attacks, it gets +`<n>`/+`<n>` until end of turn
    for each other attacking Goblin." — 2 cache-wide (Goblin Piledriver,
    Goblin Rabblemaster).
- **PAR-114 · Small residue batch — cost reduction & alternative
  costs.** 4 independently-shaped clauses, each ≥2 cards cache-wide:
  - "This spell costs `<cost>` less to cast, where X is the greatest power
    among creatures you control." — 4 cache-wide (Mitotic Ultimus, Molten
    Monstrosity, The Great Henge, The Skullspore Nexus).
  - "As an additional cost to cast this spell, discard a card or pay
    `<cost>`." — 3 cache-wide (Lightning Axe, Pumpkin Bombardment,
    Titania Rugged Rumbler).
  - "As an additional cost to cast this spell, sacrifice a creature or
    discard a card." — 2 cache-wide (Bone Shards, Minion Missile).
  - "During turns other than yours, spells you cast cost `<cost>` less to
    cast." — 2 cache-wide (Geyser Drake, Naiad of Hidden Coves).

> **PAR-107…PAR-114's card lists and counts come from a one-pass
> `parse_oracle` + `abstract_clause` scan of the full cache (the same
> classification `commander_tail_report.py` uses), cross-referenced
> against `backend/scripts/deck_coverage.py`'s uncovered-card lists for
> all 56 saved decks, 2026-09-16 at PARSER_VERSION 413 — re-run before
> starting a sub-item, same standing rule as every other ranked count in
> this file. Unlike PAR-92/PAR-98's hand-verified small batches, these
> were not individually re-diagnosed with `parser_probe.py card` before
> filing — do that first for whichever sub-item you pick up, since a
> handler's exact shape depends on details (e.g. an intervening "if"
> clause, a self- vs. target-referent) this scan doesn't capture.**

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
