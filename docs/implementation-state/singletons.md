# Singleton queue

**Re-audited 2026-11-02 (PARSER_VERSION 819): 155 rows (about 186 distinct cards) remain; every card that resolves in the cache is UNMODELED, and 5 names could not be resolved (Nick Fury, Lonis, Surrak, Neheb, Undercity — Throne of the Dead Three).** This pass removed 52 rows that had become MODELED, AUTHORED or permanently unsupported, and trimmed 4 multi-card rows. This is the remaining singleton queue, not the full unmodeled card pool; singleton/cluster membership has not been re-audited in this refresh.

Cards found, during backlog triage, to be genuinely one-of-a-kind: each
was checked with `parser_probe.py blocked` against a regex over its own
unclaimed clause and came back **SOLO on 1** with no plausible sibling
shape elsewhere in the ~35k-card cache — not merely "nobody's built it
yet," but "no other cached card would benefit from building it." That is
what earns a line here instead of a `PAR-*`/`MEC-*` ticket: this project's
own standing rule is that a ticket is for schedulable work with a real
cluster behind it, and a singleton doesn't have one — see the
`extend-parser` skill's "When to stop parsing and hand-author" and
[11_CARD_CATALOGUE_AUTHORING_GUIDE.md](../Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md).

**This is a queue, not a ticket.** Entries stay UNMODELED until someone
runs them through `hand-author-card` (or, for the handful below that need
a wholly new interactive primitive first, through `game-engine`). Before
picking one up, re-run its `parser_probe.py blocked` check — the standing
warning applies here too: a later, unrelated batch can turn a singleton
into a two-card cluster (a shared primitive built for a different card
now reaches this one too), at which point it should be **promoted out**
into a real ticket instead of hand-authored alone. Delete a row once its
card is closed (hand-authored or, having gained a sibling, promoted) —
same "closing = deleting" discipline as `BACKLOG.md`.

## Batch 1 — original hand-verified queue

Each row below was individually checked with `parser_probe.py blocked`
against a regex over its own unclaimed clause (the full admission bar
above). See `Batch 2` further down for a second, larger batch admitted by
a faster but slightly weaker automated check — read that batch's own
header before treating the two as equally verified.

| Card | Gap | Notes |
| --- | --- | --- |

The *clustered* residue these were sorted out of (2+ cards sharing one gap)
went to tickets in `docs/implementation-state/BACKLOG.md`, not to this file.

## Batch 2 — 2026-09-16 saved-deck coverage sweep

The rows below were **not** individually re-diagnosed with `parser_probe.py blocked` the way the queue above was — at this volume (1,020 cards across all 56 saved decks) that is a multi-session undertaking, tracked as an explicit follow-up rather than rushed. Instead every row passed a **mechanically equivalent, cache-wide check**: one `parse_oracle` pass over the full card cache (same `abstract_clause` normalization `commander_tail_report.py` uses) confirmed each card's unclaimed clause(s) have **no sibling anywhere in the cache** — a card with exactly one unclaimed clause unique cache-wide is listed plain; a card whose several unclaimed clauses are *each* individually unique is listed as a **compound gap** (all of them, not just one, would need a handler). A card with *any* clause that DOES cluster with another card was routed to a `PAR-*` ticket instead (PAR-99...PAR-114) or left for a future ticket batch — never listed here. Re-run the check before hand-authoring: a later batch can turn one of these into a two-card cluster, at which point promote it out per this file's own standing rule. Grouped by the saved deck each card was found uncovered in (its first non-cube deck, if it appears in more than one); `Commander Cube`/`cEDH staples`/`cEDH staples 2` cards with no non-cube deck are grouped under the cube itself. PARSER_VERSION 413.

**Re-evaluated 2026-09-29 at PARSER_VERSION 501, again 2026-09-30 at PARSER_VERSION 552** (whole file, all batches): 59 newly covered rows deleted, 17 gap cells updated to the card's current unclaimed clauses, deck counts recomputed. The exact-template test (below) still finds no shared clause, but a phrase-level sweep did: **~55 rows shared an *axis* with 4–31 other uncovered cards** and were promoted out into `BACKLOG.md` (PAR-136 blink at next end step, PAR-137 impulse draw, PAR-138 "N or more counters are put on", PAR-139 batch, MEC-106 Gift, MEC-107 expend) — their cards are named in those tickets. Re-run that sweep, not only the exact-template check, at the next re-evaluation: the exact-template check cannot see a shared *phrase* under different surrounding text.

### Commander Cube (83 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Custodi Lich | `whenever you become the monarch, target player sacrifices a creature of their choice.` |  |
| Daretti, Rocketeer Engineer | `whenever <name> enters or attacks, choose target artifact card in your graveyard. you may sacrifice an artifact. if you do, return the chosen card to the battlefield.` |  |
| Dark Salvation | `target player creates x <n>/<n> black zombie creature tokens, then up to <n> target creature gets -<n>/-<n> until end of turn for each zombie that player controls.` |  |
| Don & Leo, Problem Solvers | `at the beginning of your end step, exile up to <n> target artifact you control and up to <n> target creature you control. then return them to the battlefield under their owners' control.` |  |
| Dragon Broodmother | `at the beginning of each upkeep, create a <n>/<n> red and green dragon creature token with flying and devour <n>.` |  |
| Dragonspark Reactor | `<cost>, sacrifice <name>: it deals damage equal to the number of charge counters on it to target player and that much damage to up to <n> target creature.` |  |
| Dusk Mangler | Compound gap — `as an additional cost to cast this spell, sacrifice a creature, discard a card, or pay <n> life.`; `when <name> enters, each opponent sacrifices a creature of their choice, discards a card, and loses <n> life.` |  |
| Echocasting Symposium | `target player creates a token that's a copy of target creature you control.` |  |
| Edgar's Awakening | `when you discard this card, you may pay <cost>. when you do, return target creature card from your graveyard to your hand.` |  |
| Elenda, Saint of Dusk | `as long as your life total is greater than your starting life total, <name> gets +<n>/+<n> and has menace. <name> gets an additional +<n>/+<n> as long as your life total is at least <n> greater than your starting life total.` |  |
| Elesh Norn // The Argent Etchings | `whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller loses <n> life unless they pay <cost>.` |  |
| Emberwilde Captain | `whenever an opponent attacks you while you're the monarch, <name> deals damage to that player equal to the number of cards in their hand.` |  |
| Emeria's Call // Emeria, Shattered Skyclave | `create <n> <n>/<n> white angel warrior creature tokens with flying. non-angel creatures you control gain indestructible until your next turn.` |  |
| Empty the Laboratory | `sacrifice x zombies, then reveal cards from the top of your library until you reveal a number of zombie creature cards equal to the number of zombies sacrificed this way. put those cards onto the battlefield and the rest on the bottom of your library in a random order.` |  |
| Eris, Roar of the Storm | `this spell costs <cost> less to cast for each different mana value among instant and sorcery cards in your graveyard.` |  |
| Ezuri, Claw of Progress | Compound gap — `at the beginning of combat on your turn, put x +<n>/+<n> counters on another target creature you control, where x is the number of experience counters you have.`; `whenever a creature you control with power <n> or less enters, you get an experience counter.` |  |
| Fatestitcher | `<cost>: you may tap or untap another target permanent.` |  |
| Fear of Impostors | `when <name> enters, counter target spell. its controller manifests dread.` |  |
| Foe-Razer Regent | `whenever a creature you control fights, put <n> +<n>/+<n> counters on it at the beginning of the next end step.` |  |
| Geralf, Visionary Stitcher | `<cost>, <cost>, sacrifice another nontoken creature: create an x/x blue zombie creature token, where x is the sacrificed creature's toughness.` |  |
| Geralf, the Fleshwright | Compound gap — `whenever a zombie you control enters, put a +<n>/+<n> counter on it for each other zombie that entered the battlefield under your control this turn.`; `whenever you cast a spell during your turn other than your first spell that turn, create a <n>/<n> blue and black zombie rogue creature token.` |  |
| Gisa, the Hellraiser | Compound gap — `skeletons and zombies you control get +<n>/+<n> and have menace.`; `whenever you commit a crime, create <n> tapped <n>/<n> blue and black zombie rogue creature tokens. this ability triggers only once each turn.` |  |
| Glimmer Lens | `whenever equipped creature and at least <n> other creature attack, draw a card.` |  |
| Glimpse the Impossible | `exile the top <n> cards of your library. you may play those cards this turn. at the beginning of the next end step, if any of those cards remain exiled, put them into your graveyard, then create a <n>/<n> colorless eldrazi spawn creature token for each card put into your graveyard this way. those tokens have <name>` |  |
| Hagra Mauling // Hagra Broodpit | `this spell costs <cost> less to cast if an opponent controls no basic lands.` |  |
| Havengul Lich | `<cost>: you may cast target creature card in a graveyard this turn. when you cast it this turn, <name> gains all activated abilities of that card until end of turn.` |  |
| Highcliff Felidar | `when <name> enters, for each opponent, choose a creature with the greatest power among creatures that player controls. destroy those creatures.` |  |
| Highway Robbery | `you may discard a card or sacrifice a land. if you do, draw <n> cards.` |  |
| Ignite the Future | `exile the top <n> cards of your library. until the end of your next turn, you may play those cards. if this spell was cast from a graveyard, you may play cards this way without paying their mana costs.` |  |
| Improvisation Capstone | `exile cards from the top of your library until you exile cards with total mana value <n> or greater. you may cast any number of spells from among them without paying their mana costs.` |  |
| Increasing Devotion | `create <n> <n>/<n> white human creature tokens. if this spell was cast from a graveyard, create <n> of those tokens instead.` |  |
| Ironsoul Enforcer | `whenever <name> or a commander you control attacks alone, return target artifact card from your graveyard to the battlefield.` |  |
| Jinnie Fay, Jetmir's Second | `if you would create <n> or more tokens, you may instead create that many <n>/<n> green cat creature tokens with haste or that many <n>/<n> green dog creature tokens with vigilance.` |  |
| Juvenile Mist Dragon | `when <name> enters, for each opponent, tap up to <n> target creature that player controls. each of those creatures doesn't untap during its controller's next untap step.` |  |
| Kitesail Larcenist | `when <name> enters, for each player, choose up to <n> other target artifact or creature that player controls. for as long as <name> remains on the battlefield, the chosen permanents become treasure artifacts with <name> and lose all other abilities.` |  |
| Mana Sculpt | `counter target spell. if you control a wizard, add an amount of <cost> equal to the amount of mana spent to cast that spell at the beginning of your next main phase.` |  |
| Meteor Blast | `<name> deals <n> damage to each of x targets.` |  |
| Moonveil Regent | Compound gap — `when <name> dies, it deals x damage to any target, where x is the number of colors among permanents you control.`; `whenever you cast a spell, you may discard your hand. if you do, draw a card for each of that spell's colors.` |  |
| Moria Scavenger | `<cost>, discard a card: draw a card. if the discarded card was a creature card, amass orcs <n>.` |  |
| Nahiri's Resolve | `at the beginning of your end step, exile any number of nontoken artifacts and/or creatures you control. return those cards to the battlefield under their owner's control at the beginning of your next upkeep.` |  |
| Old Rutstein | `when <name> enters and at the beginning of your upkeep, mill a card. if a land card is milled this way, create a treasure token. if a creature card is milled this way, create a <n>/<n> green insect creature token. if a noncreature, nonland card is milled this way, create a blood token.` |  |
| Osgir, the Reconstructor | `<cost>, <cost>, exile an artifact card with mana value x from your graveyard: create <n> tokens that are copies of the exiled card. activate only as a sorcery.` |  |
| Party Thrasher | `noncreature spells you cast from exile have convoke.` |  |
| Peel from Reality | `return target creature you control and target creature you don't control to their owners' hands.` |  |
| Prosper, Tome-Bound | Compound gap — `mystic arcanum — at the beginning of your end step, exile the top card of your library. until the end of your next turn, you may play that card.`; `pact boon — whenever you play a card from exile, create a treasure token.` |  |
| Queen Allenal of Ruadach | `if <n> or more creature tokens would be created under your control, those tokens plus a <n>/<n> white soldier creature token are created instead.` |  |
| Ravenous Gigantotherium | `when <name> enters, it deals x damage divided as you choose among up to x target creatures, where x is its power. each of those creatures deals damage equal to its power to <name>.` |  |
| Ravenous Robots | `<cost>, <cost>: creature tokens you control gain haste until end of turn.` |  |
| Reconstruct History | `return up to <n> target artifact card, up to <n> target enchantment card, up to <n> target instant card, up to <n> target sorcery card, and up to <n> target planeswalker card from your graveyard to your hand.` |  |
| Red Dragon | `fire breath — when <name> enters, it deals <n> damage to each opponent.` |  |
| Rise of the Witch-king | `each player sacrifices a creature of their choice. if you sacrificed a creature this way, you may return another permanent card from your graveyard to the battlefield.` |  |
| Sarevok's Tome | `<cost>, <cost>: exile cards from the top of your library until you exile a nonland card. you may cast that card without paying its mana cost. activate only if you've completed a dungeon.` |  |
| Scampering Surveyor | `when <name> enters, search your library for a basic land card or cave card, put it onto the battlefield tapped, then shuffle.` |  |
| Scavenged Brawler | `<cost>, exile this card from your graveyard: choose target creature. put <n> +<n>/+<n> counters, a flying counter, a vigilance counter, a trample counter, and a lifelink counter on that creature. activate only as a sorcery.` |  |
| Seasoned Dungeoneer | `whenever you attack, target attacking cleric, rogue, warrior, or wizard gains protection from creatures until end of turn. it explores.` |  |
| Shadowgrange Archfiend | `when <name> enters, each opponent sacrifices a creature with the greatest power among creatures they control. you gain life equal to the greatest power among creatures sacrificed this way.` |  |
| Sheoldred // The True Scriptures | `when <name> enters, each opponent sacrifices a nontoken creature or planeswalker of their choice.` |  |
| Signature Slam | `put a +<n>/+<n> counter on target creature you control, then each modified creature you control deals damage equal to its power to target creature you don't control.` |  |
| Simic Manipulator | `<cost>, remove <n> or more +<n>/+<n> counters from <name>: gain control of target creature with power less than or equal to the number of +<n>/+<n> counters removed this way.` |  |
| Slash the Ranks | `destroy all creatures and planeswalkers except for commanders.` |  |
| Slimefoot and Squee | `<cost>, sacrifice a saproling: return this card and up to <n> other target creature card from your graveyard to the battlefield. activate only as a sorcery.` |  |
| Smoldering Egg // Ashmouth Dragon | `whenever you cast an instant or sorcery spell, put a number of ember counters on <name> equal to the amount of mana spent to cast that spell. then if <name> has <n> or more ember counters on it, remove them and transform <name>.` |  |
| Smuggler's Surprise | Compound gap — `+ <cost> — creatures you control with power <n> or greater gain hexproof and indestructible until end of turn.`; `+ <cost> — mill <n> cards. you may put up to <n> creature and/or land cards from among the milled cards into your hand.`; `+ <cost> — you may put up to <n> creature cards from your hand onto the battlefield.` |  |
| Soulherder | `whenever a creature is exiled from the battlefield, put a +<n>/+<n> counter on <name>.` |  |
| Spear of Heliod | `<cost>, <cost>: destroy target creature that dealt damage to you this turn.` |  |
| Spinerock Tyrant | `whenever you cast an instant or sorcery spell with a single target, you may copy it. if you do, those spells gain wither. you may choose new targets for the copy.` |  |
| Synchronized Charge | `distribute <n> +<n>/+<n> counters among <n> or <n> target creatures you control. creatures you control with counters on them gain vigilance and trample until end of turn.` |  |
| The Eternal Wanderer | Compound gap — `+<n>: exile up to <n> target artifact or creature. return that card to the battlefield under its owner's control at the beginning of that player's next end step.`; `no more than <n> creature can attack <name> each combat.`; `−<n>: for each player, choose a creature that player controls. each player sacrifices all creatures they control not chosen this way.` |  |
| The Raven Man | `at the beginning of each end step, if a player discarded a card this turn, create a <n>/<n> black bird creature token with flying and <name>` |  |
| Thousand Moons Smithy // Barracks of the Thousand | `at the beginning of your first main phase, you may tap <n> untapped artifacts and/or creatures you control. if you do, transform <name>.` |  |
| Three Steps Ahead | Compound gap — `+ <cost> — counter target spell.`; `+ <cost> — create a token that's a copy of target artifact or creature you control.`; `+ <cost> — draw <n> cards, then discard a card.` |  |
| Thrull Parasite | `<cost>, pay <n> life: remove a counter from target nonland permanent.` |  |
| Tivash, Gloom Summoner | `at the beginning of your end step, if you gained life this turn, you may pay x life, where x is the amount of life you gained this turn. if you do, create an x/x black demon creature token with flying.` |  |
| Tom Bombadil | Compound gap — `as long as there are <n> or more lore counters among sagas you control, <name> has hexproof and indestructible.`; `whenever the final chapter ability of a saga you control resolves, reveal cards from the top of your library until you reveal a saga card. put that card onto the battlefield and the rest on the bottom of your library in a random order. this ability triggers only once each turn.` |  |
| Tomb of Horrors Adventurer | `whenever you cast your second spell each turn, copy it. if you've completed a dungeon, copy that spell twice instead. you may choose new targets for the copies.` |  |
| Ugin, the Spirit Dragon | Compound gap — `−<n>: you gain <n> life, draw <n> cards, then put up to <n> permanent cards from your hand onto the battlefield.`; `−x: exile each permanent with mana value x or less that's <n> or more colors.` |  |
| Unexplained Absence | `for each player, exile up to <n> target nonland permanent that player controls. for each permanent exiled this way, its controller cloaks the top card of their library.` |  |
| Virtue of Strength // Garenbrig Growth | `if you tap a basic land for mana, it produces <n> times as much of that mana instead.` |  |
| Warden of the Grove | `whenever another nontoken creature you control enters, it endures x, where x is the number of counters on <name>.` |  |
| White Plume Adventurer | `at the beginning of each opponent's upkeep, untap a creature you control. if you've completed a dungeon, untap all creatures you control instead.` |  |
| Wildfire Devils | `when <name> enters and at the beginning of your upkeep, choose a player at random. that player exiles an instant or sorcery card from their graveyard. copy that card. you may cast the copy without paying its mana cost.` |  |
| Windswift Slice | `target creature you control deals damage equal to its power to target creature you don't control. create a number of <n>/<n> green elf warrior creature tokens equal to the amount of excess damage dealt this way.` |  |
| Zameck Guildmage | `<cost>: this turn, each creature you control enters with an additional +<n>/+<n> counter on it.` |  |


## Batch 3 — 2026-09-21 re-evaluation of PAR-99…PAR-113 (PARSER_VERSION 447)

Found by decomposing the wrapper template `equipped creature has <name>`
(`BACKLOG.md`'s PAR-109), which the batch-1 sweep had counted as a 6-card
cluster: the quoted-grant shell (`static_handlers._ATTACHED_QUOTED_GRANT_RE`)
already works, so each card is blocked only by its own **inner** ability. Each
inner ability below was searched cache-wide across every unclaimed clause
(`parser_probe.py blocked`-equivalent regex over the distinctive text) and came
back on this card alone. The other two Equipment cards in that template are
*not* singletons — The Masamune belongs to the 32-card "triggers an
additional time" axis and Stormforged Armor pairs with Kari Zev on
"conjure … tapped and attacking" (both noted under PAR-109).

| Card | Gap | Notes |
| --- | --- | --- |
| Shuriken | Granted "{T}, Unattach ~: ~ deals 2 damage to target creature. That creature's controller gains control of ~ unless it was unattached from a Ninja." | A cost that unattaches the source, plus a control-change conditioned on what the Equipment was attached to. Elbrus, the Binding Blade shares the word "unattach" but not the shape (its trigger unattaches then transforms). |
| Fishing Pole | Compound gap — granted `{1}, {T}, tap ~: put a bait counter on ~.`; `Whenever equipped creature becomes untapped, remove a bait counter from ~. If you do, create a 1/1 blue Fish creature token.` | Both clauses are unique cache-wide ("bait counter" appears on no other card); the second is a becomes-untapped trigger on the equipped creature, which handler-recipe.md lists as deliberately absent from `_TRIGGER_VERBS` (re-check whether the engine fires a becomes-untapped event before hand-authoring). |

## Batch 4 — 2026-09-30 PAR-128 leftovers (PARSER_VERSION 550)

The target/group-grammar slots PAR-128 owned are closed; this card parses everything up to its own unique clause (`parser_probe.py blocked 'shares a mana value with it'` → SOLO on 1).

| Card | Gap | Notes |
| --- | --- | --- |
| The Crimson Avenger | `When ~ enters, choose target spell an opponent controls. Reveal cards from the top of your library until you reveal a card that shares a mana value with it. Cast that card without paying its mana cost. Then shuffle your library.` | The "target spell an opponent controls" slot now parses (`spell_you_dont_control`); the gap left is reveal-until-*shares a mana value with the chosen spell* + free cast, unique cache-wide. |

## Batch 5 — 2026-09-30 re-evaluation of PAR-103/PAR-113 (PARSER_VERSION 552)

Left behind when PAR-119 (graveyard arrivals) and the combat-trigger rows closed the bulk of those tickets; each remaining clause is unique cache-wide (`parser_probe.py blocked` on its distinctive phrase → SOLO 1).

| Card | Gap | Notes |
| --- | --- | --- |
| Guile | `If a spell or ability you control would counter a spell, instead exile that spell and you may play that card without paying its mana cost.` | A counter-replacement that exiles and grants a free play; PAR-103's shuffle clause on the same card now parses. |
| Human Torch | `Whenever ~ attacks, you may pay {r}{g}{w}{u}. If you do, until end of turn, whenever he deals combat damage to an opponent, he deals that much damage to each other opponent.` | A pay-gated delayed trigger; the shape of PAR-113's closed "it deals that much damage to each other opponent" bullet, but the referent is granted until end of turn rather than standing. |
| Kosei, Penitent Warlord | `As long as ~ is enchanted, equipped, and has a counter on it, ~ has "Whenever ~ deals combat damage to an opponent, you draw that many cards and ~ deals that much damage to each other opponent."` | A three-part conditional over the host's own attachments and counters, wrapping a granted trigger. |
| Arni Metalbrow | `Whenever a creature you control attacks or enters attacking, you may pay {1}{R}. If you do, you may put a creature card with mana value less than that creature's mana value from your hand onto the battlefield tapped and attacking.` | Two gaps: no "enters attacking" event (`put_onto_battlefield_attacking` fires nothing, RULE 508.3a) and a mana-value bound relative to the triggering creature. PAR-148 closed around it. |
| Boulder Jockey | `Whenever ~ attacks, you may pay {D}. If you do, create a 3/3 … token named Boulder that's tapped and attacking. Sacrifice that token at the beginning of the next end step.` | `{D}` is a land-drop cost ("give up one potential land drop this turn") — no such mana symbol or land-drop accounting exists. The token half is the parser's since PAR-148. |

## Batch 6 — 2026-10-12 PAR-151 coin-flip close-out (PARSER_VERSION 632)

Each gap checked with `parser_probe.py blocked` over its own clause: SOLO on 1.

| Card | Gap | Notes |
| --- | --- | --- |
| Crooked Scales | `… unless you pay {3}. if you do, repeat this process.` | Targets must be kept across the repeat, with a payment mid-loop; `RepeatProcessEffect` runs without targets. |
| Wirefly Hive | `destroy all permanents named wirefly.` | `combat.matches_object_filter` has no `name` filter; the flip half is modeled. |

## Batch 7 — 2026-10-19 PAR-132 close-out (PARSER_VERSION 692)

Sized with `parser_probe.py blocked` at v691–692: each row's cards share a phrase but not a body, so none forms a cluster. Re-run the check before hand-authoring.

| Card | Gap | Notes |
| --- | --- | --- |
| Decoy Gambit, Kitesail Larcenist, Mega Flare, Tolarian Contempt | `for each opponent, choose up to one target … that player controls` + chosen-set body | Per-round chosen-set referent; four different bodies. |
| Alpha Brawl, Deputy of Detention | prior-target group bodies | Three distinct shapes. |
| Portal Mage, Windshaper Planetar, Portal Manipulator, Arni Metalbrow, Nick Fury, Shark Shredder, Summoner's Grimoire, Noble Ox | `enters … attacking` / reselect the attacked player | Eight distinct bodies. |
| Nahiri's Lithoforming, Gluttonous Hellkite, Empty the Laboratory, Lonis | `sacrifice x <noun>` count form + this-way tally | Builds on the `sacrificed_this_way` window. |
| Boneyard Desecrator, Thallid Omnivore, Dargo, Explosive Singularity, Burn at the Stake, Devouring Greed, Devouring Rage | tallies over a sacrifice/tap paid as a cost | The `mark_event_log` window opens at resolution, after costs. |
| Warren Weirding, Reign of the Pit, Shadowgrange Archfiend, Ill-Timed Explosion, Reckless Handling | subtype condition / power or mana-value measured over the this-way pool | Reckless Handling also needs a search-clause body. |
| Unsettled Mariner, Parnesse, Rayne, Surrak | `you or a permanent you control becomes the target` heads | Distinct bodies. |
| Nadu, Winged Wisdom | quoted grant of a becomes-the-target trigger | |
| Borborygmos and Fblthp, Miasma Demon, Neheb | reflexive `when you discard one or more cards this way` | |
| Scarwood Bandits, Charisma | control `for as long as ~ remains on the battlefield` | Blocked on target filters, not the duration. |

## Batch 8 — 2026-10-19 PAR-166 close-out (PARSER_VERSION 694)

Sized with `parser_probe.py` at v693–694. Re-run the check before hand-authoring; the engine-shaped groups are listed in `Done_Backend.md` "PAR-166".

| Card | Gap | Notes |
| --- | --- | --- |
| Eunuchs' Intrigues, Goblin War Cry | opponent chooses a creature; "other creatures they control can't block this turn" | Same clause on both; restriction body over the complement of the choice. |
| Fell Beast's Shriek | each opponent chooses a creature; "tap and goad the chosen creatures" | |
| Banshee, Eternal Flame | "half x damage, rounded …, to you" | |
| Catacomb Dragon, Freyalise Supplicant | half of a creature's power | Different referents (blocked creature vs. sacrificed creature). |
| Singularity Rupture, Colorless Ultimatum | mill/exile half a library | Different recipients and zones. |
| Heartless Hidetsugu | halved life, other bodies | |
| Essence Pulse | "each creature gets -x/-x" | Unparsed even with a fixed number. |
| Leyline of the Guildpact | "each nonland permanent you control is all colors" | |
| Ghostfire | "~ is colorless" inside a spell body | |
| Ezzaroot Channeler, Licia | per-life cost reduction | |


## Batch 9 — 2026-10-20 PAR-175 close-out (PARSER_VERSION 712)

Sized during PAR-175 M4b: "the permanent(s) for which …" occurs on this card only. See `Done_Backend.md` "Clause linkage across a sequence (PAR-175)".

| Card | Gap | Notes |
| --- | --- | --- |
| Scrambleverse | "for each nonland permanent, choose a player at random. then each player gains control of each permanent for which they were chosen. untap those permanents." | Needs a random player per permanent and control changes by that assignment; no engine primitive for a per-object random choice yet. |


## Batch 10 — 2026-10-20 PAR-176 close-out (PARSER_VERSION 713)

Each card's "Activate only …" sentence is otherwise claimed; only its condition has no `static_conditions` primitive. Arcum's Sleigh and Kjeldoran Guard share one shape: promote them together. See `Done_Backend.md` "\"Activate only …\" restriction sentences (PAR-176)".

| Card | Gap | Notes |
| --- | --- | --- |
| Arcum's Sleigh, Kjeldoran Guard | "only if defending player controls a snow land" | Needs a defending-player condition. |
| Cinder Crawler | "only if ~ is blocked" | "Blocked" must persist after its blockers leave (RULE 509.1h); `blocked_by` is cleared. |
| Sea Troll | "only if ~ blocked or was blocked by a blue creature this turn" | Per-turn block history with the blocker's color. |
| Ashen Ghoul | "only if three or more creature cards are above ~ in your graveyard" | Graveyard order position. |
| Matzalantli | permanent types among cards in your graveyard | Distinct card-type count over a zone. |
| Kitsune Bonesetter | "more cards in hand than each opponent" | Hand-size comparison against every opponent. |
| Skyblade's Boon | "only if ~ is on the battlefield or in your graveyard" | Zone-of-source condition. |
| Blitzball | an opponent was dealt combat damage by a legendary creature this turn | Per-turn damage history by source type. |
| Bonecache Overseer | cards left your graveyard this turn, or you sacrificed a Food | Per-turn zone-exit and sacrifice history. |
| Deadhead | "only if an opponent isn't touching their hand" | Real-world action; likely `NEVER_SUPPORTED`. |
| Kongming's Contraptions | "only if you've been attacked this step" | Per-step attack history. |
| Rocket Launcher | controlled continuously since your most recent turn began | Summoning-sickness-style control timestamp for a noncreature. |
| Sarevok's Tome | "only if you've completed a dungeon" | Completed-dungeon flag per player. |

## Batch 11 — 2026-10-29 status audit: flip cards, battles, Rooms and dungeons (PARSER_VERSION 809)

Explicitly queued from the open card-text coverage in `status.de.js` / `status.en.js`. Current cache data was read without modification; every actionable card below is UNMODELED and not AUTHORED. These are card-specific follow-ups, **not yet verified singletons**: no cache-wide sibling/cluster admission check was performed. Before implementation, recheck the current verdict and shared shapes; route shared work to an existing or new parser ticket. The existing Invasion of Tarkir row was moved here to avoid duplication. Counts cover this batch only, not the historical queue above.

### Flip cards (10 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Akki Lavarunner // Tok-Tok, Volcano Born | `if a red source would deal damage to a player, it deals that much damage plus 1 to that player instead.` | Current unclaimed clauses; singleton/cluster check pending. |
| Budoka Gardener // Dokai, Weaver of Life | `{4}{g}{g}, {t}: create an x/x green elemental creature token, where x is the number of lands you control.` | Current unclaimed clauses; singleton/cluster check pending. |
| Curse of the Fire Penguin // Curse of the Fire Penguin Creature | `~ consumes and confuses enchanted creature.`; `when ~ dies, return curse of the fire penguin to the battlefield.` | Current unclaimed clauses; singleton/cluster check pending. |
| Erayo, Soratami Ascendant // Erayo's Essence | `whenever the fourth spell of a turn is cast, flip ~.` | Current unclaimed clauses; singleton/cluster check pending. |
| Homura, Human Ascendant // Homura's Essence | `when ~ dies, return it to the battlefield flipped.`; `creatures you control get +2/+2 and have flying and "{r}: ~ gets +1/+0 until end of turn."` | Current unclaimed clauses; singleton/cluster check pending. |
| Kitsune Mystic // Autumn-Tail, Kitsune Sage | `at the beginning of the end step, if ~ is enchanted by 2 or more auras, flip it.`; `{1}: attach target aura attached to a creature to another creature.` | Current unclaimed clauses; singleton/cluster check pending. |
| Nezumi Graverobber // Nighteyes the Desecrator | `{1}{b}: exile target card from an opponent's graveyard. if no cards are in that graveyard, flip ~.` | Current unclaimed clauses; singleton/cluster check pending. |
| Nezumi Shortfang // Stabwhisker the Odious | `{1}{b}, {t}: target opponent discards a card. then if that player has no cards in hand, flip ~.`; `at the beginning of each opponent's upkeep, that player loses 1 life for each card fewer than 3 in their hand.` | Current unclaimed clauses; singleton/cluster check pending. |
| Sasaya, Orochi Ascendant // Sasaya's Essence | `reveal your hand: if you have 7 or more land cards in your hand, flip ~.`; `whenever a land you control is tapped for mana, add an additional 1 mana of any type that land produced for each other land you control with the same name as it.` | Current unclaimed clauses; singleton/cluster check pending. |
| Student of Elements // Tobita, Master of Winds | `when ~ has flying, flip it.` | Current unclaimed clauses; singleton/cluster check pending. |

### Battles (11 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Invasion of Alara // Awaken the Maelstrom | `when ~ enters, exile cards from the top of your library until you exile 2 nonland cards with mana value 4 or less. you may cast 1 of those 2 cards without paying its mana cost. put 1 of them into your hand. then put the other cards exiled this way on the bottom of your library in a random order.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Arcavios // Invocation of the Founders | `when ~ enters, search your library, graveyard, and/or outside the game for an instant or sorcery card you own, reveal it, and put it into your hand. if you search your library this way, shuffle.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Azgol // Ashen Reaper | `when ~ enters, target player sacrifices a creature or planeswalker of their choice and loses 1 life.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Gobakhan // Lightshield Array | `when ~ enters, look at target opponent's hand. you may exile a nonland card from it. for as long as that card remains exiled, its owner may play it. a spell cast this way costs {2} more to cast.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Lorwyn // Winnowing Forces | `when ~ enters, destroy target non-elf creature an opponent controls with power x or less, where x is the number of lands you control.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Pyrulea // Gargantuan Slabhorn | `when ~ enters, scry 3, then reveal the top card of your library. if it's a land or double-faced card, draw a card.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Ravnica // Guildpact Paragon | `when ~ enters, exile target nonland permanent an opponent controls that isn't exactly 2 colors.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Tarkir // Defiant Thundermaw | `when ~ enters, reveal any number of dragon cards from your hand. when you do, ~ deals x plus 2 damage to any other target, where x is the number of cards revealed this way.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Theros // Ephara, Ever-Sheltering | `when ~ enters, search your library for an aura, god, or demigod card, reveal it, put it into your hand, then shuffle.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Tolvada // The Broken Sky | `when ~ enters, return target nonbattle permanent card from your graveyard to the battlefield.` | Current unclaimed clauses; singleton/cluster check pending. |
| The Battle of Dragon Brothers // Fate Reforged | `when ~ enters, choose bolas or ugin.`; `• bolas — destroy all creatures.`; `• ugin — manifest the top 3 cards of your library.` | Current unclaimed clauses; singleton/cluster check pending. |

### Rooms (6 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Central Elevator // Promising Stairs | `when you unlock this door, search your library for a room card that doesn't have the same name as a room you control, reveal it, put it into your hand, then shuffle.` | Current unclaimed clauses; singleton/cluster check pending. |
| Charred Foyer // Warped Space | `once each turn, you may pay {0} rather than pay the mana cost for a spell you cast from exile.` | Current unclaimed clauses; singleton/cluster check pending. |
| Dazzling Theater // Prop Room | `creature spells you cast have convoke.`; `untap each creature you control during each other player's untap step.` | Current unclaimed clauses; singleton/cluster check pending. |
| Dollmaker's Shop // Porcelain Gallery | `creatures you control have base power and toughness each equal to the number of creatures you control.` | Current unclaimed clauses; singleton/cluster check pending. |
| Greenhouse // Rickety Gazebo | `when you unlock this door, mill 4 cards, then return up to 2 permanent cards from among them to your hand.` | Current unclaimed clauses; singleton/cluster check pending. |
| Walk-In Closet // Forgotten Cellar | `when you unlock this door, you may cast spells from your graveyard this turn, and if a card would be put into your graveyard from anywhere this turn, exile it instead.` | Current unclaimed clauses; singleton/cluster check pending. |

### Dungeon room text (1 room)

| Card / room | Gap | Notes |
| --- | --- | --- |
| Undercity — Throne of the Dead Three | `Reveal the top ten cards of your library. Put a creature card from among them onto the battlefield with three +1/+1 counters on it. It gains hexproof until your next turn. Then shuffle.` | Room effect body remains unmodeled; the dungeon engine and room graph exist. Singleton/cluster check pending. |

### Unsupported Rooms (reference only; not actionable queue entries)

These explain the remaining Room coverage denominator and must not be treated as implementation work: `Crude Abattoir // Unsavory Kitchen`, `Solitary Study // Endless Corridor`. Both return `NEVER_SUPPORTED` because their Alchemy halves are a permanent non-goal.
