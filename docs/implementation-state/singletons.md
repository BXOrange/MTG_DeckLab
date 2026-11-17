# Singleton queue

**Queue re-audited against the parser and card registry on 2026-11-11: 143 rows remain (not counting the 50-row Star Trek section added 2026-11-10).** The 2026-11-02 audit at PARSER_VERSION 819 found 155 rows; completed cards are removed after runtime validation. Grouped rows and duplicate names remain historical queue entries, not a distinct-card coverage count.

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

### Commander Cube (36 cards)

Saved-deck audit on 2026-11-12. Newly found gaps are requested intake; recheck shared parser shapes before treating them as confirmed singletons.

| Card | Gap | Notes |
| --- | --- | --- |
| Anje Falkenrath | `whenever you discard a card, if it has madness, untap ~.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Barrowgoyf | `whenever ~ deals combat damage to a player, you may mill that many cards. if you do, you may put a creature card from among them into your hand.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Bow of Nylea | `{1}{g}, {t}: choose 1 —; • put a +1/+1 counter on target creature.; • ~ deals 2 damage to target creature with flying.; • you gain 3 life.; • put up to 4 target cards from your graveyard on the bottom of your library in any order.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Champions of Minas Tirith | `at the beginning of combat on each opponent's turn, if you're the monarch, that opponent may pay {x}, where x is the number of cards in their hand. if they don't, they can't attack you this combat.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Chaos Dragon | `at the beginning of combat on your turn, each player rolls a d20. if 1 or more opponents had the highest result, ~ can't attack those players or planeswalkers they control this combat.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Charming Prince | `when ~ enters, choose 1 —; • scry 2.; • you gain 3 life.; • exile another target creature you own. return it to the battlefield under your control at the beginning of the next end step.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Cone of Cold | `roll a d20.; 1 \| tap all creatures your opponents control; 10 \| tap all creatures your opponents control. those creatures don't untap during their controllers' next untap steps; 20 \| tap all creatures your opponents control. those creatures don't untap during their controllers' next untap steps. until your next turn, creatures your opponents control enter tapped` | Saved deck: Commander Cube. Shared-shape review pending. |
| Deadly Plot | `choose 1 —; • destroy target creature or planeswalker.; • return target zombie creature card from your graveyard to the battlefield tapped.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Grimgrin, Corpse-Born | `~ enters tapped and doesn't untap during your untap step.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Kaya's Guile | `choose 2 —; • each opponent sacrifices a creature of their choice.; • exile all opponents' graveyards.; • create a 1/1 white and black spirit creature token with flying.; • you gain 4 life.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Kura, the Boundless Sky | `when ~ dies, choose 1 —; • search your library for up to 3 land cards, reveal them, put them into your hand, then shuffle.; • create an x/x green spirit creature token, where x is the number of lands you control.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Lonis, Genetics Expert | `whenever 1 or more +1/+1 counters are put on ~, investigate that many times.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Master Biomancer | `each other creature you control enters with a number of additional +1/+1 counters on it equal to ~'s power and as a mutant in addition to its other types.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Pick Your Poison | `choose 1 —; • each opponent sacrifices an artifact of their choice.; • each opponent sacrifices an enchantment of their choice.; • each opponent sacrifices a creature with flying of their choice.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Reverse the Polarity | `choose 1 —; • counter all other spells.; • switch each creature's power and toughness until end of turn.; • creatures can't be blocked this turn.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Rise of the Witch-king | `each player sacrifices a creature of their choice. if you sacrificed a creature this way, you may return another permanent card from your graveyard to the battlefield.` |  |
| Season of Loss | `choose up to 5 {p} worth of modes. you may choose the same mode more than once.; {p} — each player sacrifices a creature of their choice.; {p}{p} — draw a card for each creature that died under your control this turn.; {p}{p}{p} — each opponent loses x life, where x is the number of creature cards in your graveyard.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Seasoned Dungeoneer | `whenever you attack, target attacking cleric, rogue, warrior, or wizard gains protection from creatures until end of turn. it explores.` |  |
| Seraphic Greatsword | `whenever equipped creature attacks the player with the most life or tied for most life, create a 4/4 white angel creature token with flying that's tapped and attacking that player.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Shadow in the Warp | `the first creature spell you cast each turn costs {2} less to cast.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Shadowgrange Archfiend | `when <name> enters, each opponent sacrifices a creature with the greatest power among creatures they control. you gain life equal to the greatest power among creatures sacrificed this way.` |  |
| Sheoldred // The True Scriptures | `when <name> enters, each opponent sacrifices a nontoken creature or planeswalker of their choice.` |  |
| Simic Manipulator | `<cost>, remove <n> or more +<n>/+<n> counters from <name>: gain control of target creature with power less than or equal to the number of +<n>/+<n> counters removed this way.` |  |
| Sorcerer Class | `creatures you control have "{t}: add {u} or {r}. spend this mana only to cast an instant or sorcery spell or to gain a class level."; whenever you cast an instant or sorcery spell, that spell deals damage to each opponent equal to the number of instant and sorcery spells you've cast this turn.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Spinerock Tyrant | `whenever you cast an instant or sorcery spell with a single target, you may copy it. if you do, those spells gain wither. you may choose new targets for the copy.` |  |
| Starfall Invocation | `destroy all creatures. if the gift was promised, return a creature card put into your graveyard this way to the battlefield under your control.` | Saved deck: Commander Cube. Shared-shape review pending. |
| The Eternal Wanderer | Compound gap — `+<n>: exile up to <n> target artifact or creature. return that card to the battlefield under its owner's control at the beginning of that player's next end step.`; `no more than <n> creature can attack <name> each combat.`; `−<n>: for each player, choose a creature that player controls. each player sacrifices all creatures they control not chosen this way.` |  |
| Thousand Moons Smithy // Barracks of the Thousand | `at the beginning of your first main phase, you may tap <n> untapped artifacts and/or creatures you control. if you do, transform <name>.` |  |
| Tivash, Gloom Summoner | `at the beginning of your end step, if you gained life this turn, you may pay x life, where x is the amount of life you gained this turn. if you do, create an x/x black demon creature token with flying.` |  |
| Tom Bombadil | Compound gap — `as long as there are <n> or more lore counters among sagas you control, <name> has hexproof and indestructible.`; `whenever the final chapter ability of a saga you control resolves, reveal cards from the top of your library until you reveal a saga card. put that card onto the battlefield and the rest on the bottom of your library in a random order. this ability triggers only once each turn.` |  |
| Tomb of Horrors Adventurer | `whenever you cast your second spell each turn, copy it. if you've completed a dungeon, copy that spell twice instead. you may choose new targets for the copies.` |  |
| Ugin, the Spirit Dragon | Compound gap — `−<n>: you gain <n> life, draw <n> cards, then put up to <n> permanent cards from your hand onto the battlefield.`; `−x: exile each permanent with mana value x or less that's <n> or more colors.` |  |
| Underdark Rift | `{5}, {t}, exile ~: roll a d10. put target artifact, creature, or planeswalker into its owner's library just beneath the top x cards of that library, where x is the result. activate only as a sorcery.` | Saved deck: Commander Cube. Shared-shape review pending. |
| Unexplained Absence | `for each player, exile up to <n> target nonland permanent that player controls. for each permanent exiled this way, its controller cloaks the top card of their library.` |  |
| Virtue of Strength // Garenbrig Growth | `if you tap a basic land for mana, it produces <n> times as much of that mana instead.` |  |
| Wildfire Devils | `when <name> enters and at the beginning of your upkeep, choose a player at random. that player exiles an instant or sorcery card from their graveyard. copy that card. you may cast the copy without paying its mana cost.` |  |


## Batch 7 — 2026-10-19 PAR-132 close-out (PARSER_VERSION 692)

Sized with `parser_probe.py blocked` at v691–692: each row's cards share a phrase but not a body, so none forms a cluster. Re-run the check before hand-authoring.

| Card | Gap | Notes |
| --- | --- | --- |
| Decoy Gambit; Mega Flare; Tolarian Contempt | `for each opponent, choose up to one target … that player controls` + chosen-set body | Per-round chosen-set referent; three different bodies. |
| Alpha Brawl, Deputy of Detention | prior-target group bodies | Three distinct shapes. |
| Windshaper Planetar; Portal Manipulator; Arni Metalbrow; Nick Fury, Spymaster; Shark Shredder, Killer Clone; Summoner's Grimoire; Noble Ox | `enters … attacking` / reselect the attacked player | Eight distinct bodies. |
| Nahiri's Lithoforming; Gluttonous Hellkite; Lonis, Cryptozoologist | `sacrifice x <noun>` count form + this-way tally | Builds on the `sacrificed_this_way` window. |
| Boneyard Desecrator; Thallid Omnivore; Dargo, the Shipwrecker; Explosive Singularity; Burn at the Stake; Devouring Greed; Devouring Rage | tallies over a sacrifice/tap paid as a cost | The `mark_event_log` window opens at resolution, after costs. |
| Warren Weirding; Reign of the Pit; Shadowgrange Archfiend; Ill-Timed Explosion; Reckless Handling | subtype condition / power or mana-value measured over the this-way pool | Reckless Handling also needs a search-clause body. |
| Parnesse, the Subtle Brush; Surrak, Elusive Hunter | `you or a permanent you control becomes the target` heads | Distinct bodies. |
| Nadu, Winged Wisdom | quoted grant of a becomes-the-target trigger | |
| Borborygmos and Fblthp; Miasma Demon; Neheb, Dreadhorde Champion | reflexive `when you discard one or more cards this way` | |
| Scarwood Bandits; Charisma | control `for as long as ~ remains on the battlefield` | Blocked on target filters, not the duration. |

## Batch 11 — 2026-10-29 status audit: flip cards, battles, Rooms and dungeons (PARSER_VERSION 809)

Explicitly queued from the open card-text coverage in `status.de.js` / `status.en.js`. Current cache data was read without modification; every actionable card below is UNMODELED and not AUTHORED. These are card-specific follow-ups, **not yet verified singletons**: no cache-wide sibling/cluster admission check was performed. Before implementation, recheck the current verdict and shared shapes; route shared work to an existing or new parser ticket. The existing Invasion of Tarkir row was moved here to avoid duplication. Counts cover this batch only, not the historical queue above.

### Quantity-threshold head residue (PAR-231 close, PARSER_VERSION 833)

| Card | Gap | Notes |
| --- | --- | --- |
| Deeproot Pilgrimage | `whenever 1 or more nontoken merfolk you control become tapped` | No batched tap event. |
| Fblthp, Impossibly Lost | `when 1 or more of your opponents are dealt combat damage during your turn` | Plus its win-on-empty-library and shuffle-into-library body. |
| Hezrou // Demonic Stench | `whenever 1 or more creatures you control become blocked` | Aggregate becomes-blocked across attackers; body names "each blocking creature". |
| Invisible Woman, Sue Storm | `whenever you put 1 or more +1/+1 counters on 1 or more other heroes you control` | Multi-recipient counter batch (the v832 head reads one recipient). |
| Ob Nixilis, Captive Kingpin | `whenever 1 or more opponents each lose exactly 1 life` | Exact-amount life-loss batch. |
| Party Dude | `whenever 1 or more of your opponents are attacked` | Defender-side attack head, any number of attacked opponents. |
| Seifer, Balamb Rival | `whenever a creature attacking 1 of your opponents becomes blocked by 2 or more creatures` | Attacker filter by defender plus the v831 `related_min`. |
| Sharae of Numbing Depths | `whenever you tap 1 or more untapped creatures your opponents control` (once each turn) | No tap-by-you event batch. |
| The Red Terror | `whenever a red source you control deals damage to 1 or more permanents and/or players` | Per-source damage batch with a color filter (the v833 batch is grouped by recipient). |
| Zone of Flame | `whenever 1 or more cards enter or leave enchanted zone` | Enchant-zone aura; check `DEFERRED.md` before work. |
| The War Doctor | `whenever 1 or more other permanents phase out and whenever 1 or more other cards are put into exile from anywhere` | Double head; phase-out batch missing, exile half exists (v833). |
| Hero of Bretagard; Ranar the Ever-Watchful | `whenever 1 or more cards are put into exile from your hand or a spell or ability you control exiles 1 or more permanents from the battlefield` | Shared pair, both blocked by other clauses as well; promote together once those land. |
| The Heron Moon | body: release counter, at 13 or more sacrifice it and cast a copy of Emrakul, the Promised End | Head parses (v833 exile batch). |
| Ketramose, the New Dawn | `~ can't attack or block unless there are 7 or more cards in exile` | Head parses (v833). |
| Breeches, Brazen Plunderer | body: `exile the top card of each of those opponents' libraries ...` | Head parses (v833 damage batch). |
| Screeching Scorchbeast | body: `you may create that many ... do this only once each turn` | Head and `nonland_count` exist (v832). |
| Sand Scout | body: the `red, green, and white` token | Head parses (v832). |
| Flummoxed Cyclops | body: `can't block this combat` | Head parses (v831). |

### Filter-slot residue (PAR-281 close, PARSER_VERSION 917)

Both rows were checked against the shared `stack_source_filter` (`targeting.stack_source_matches`) and do not fit it without new engine state; each is solo on 1 in the cache.

| Card | Gap | Notes |
| --- | --- | --- |
| The Peregrine Dynamo | `{1}, {t}: copy target activated or triggered ability you control from another legendary source that's not a commander.` | `stack_source_filter` knows only `card_types`/`colorless`. Needs "another" (compare with the copying ability's own source: `stack_source_matches` is never handed it), a `legendary` supertype key and an `is_commander` key. Small hand-authored `copy_target_ability` with its own filter, or extend the three keys when a second card appears. |
| Ayesha Tanaka | `{t}: counter target activated ability from an artifact source unless that ability's controller pays {w}.` | The source filter ("from an artifact source") is already carried (Rust); the open part is the "unless that ability's controller pays {W}" rider, which `counter_ability` has no param for (the spell-side `counter` has `unless_pays`). Hand-author with `counter_ability` + unless-pay, or add the param on a second card. |

### Defending-player residue (PAR-315 close, PARSER_VERSION 936)

Each needs its own primitive beyond the PAR-313/315 defending-player referent (`attack_scope.defending_player_id`, `core._combat_defending_player`, player scope `defending_player`).

| Card | Gap | Notes |
| --- | --- | --- |
| Coral Fighters | look at the top card of defending player's library; you may put it on the bottom | peek-and-bottom on another player's library |
| Bone Dancer | put the top creature card of defending player's graveyard onto the battlefield under your control; ~ assigns no combat damage | reanimate from another graveyard, top creature card |
| Radha's Firebrand | target creature defending player controls with power less than ~'s power can't block | dynamic power comparison in a target filter |
| Yare | target creature defending player controls ... can block additional creatures | block-count change |
| Blaze of Glory | target creature defending player controls can block any number of creatures; blocks each attacking creature if able | block-count plus forced block of all |
| False Orders | remove target creature defending player controls from combat; creatures it was blocking that had become blocked by only that creature become unblocked; you may have it block an attacking creature | remove from combat plus reassigned block |
| Cyclops Gladiator | ~ deals damage equal to its power to target creature defending player controls and that creature deals damage equal to its power to ~ | mutual fight-like damage outside fight |
| Purifying Dragon | rider "if that creature is a Zombie" on damage to a creature defending player controls | per-target subtype rider |
| Sensational Spider-Man | stun counters on a creature defending player controls | stun counter placement on a defender's creature |
| Silumgar, the Drifting Death | creatures defending player controls get -1/-1 until end of turn | mass P/T on a defender-scoped group |
| Storm the Citadel, Icingdeath, Frost Tyrant | grant a combat trigger naming defending player from an unrelated head | not examined beyond the probe line |
| Kazuul, Tyrant of the Cliffs | "unless that creature's controller pays {3}" on a creature attacking you | defender-relative tax |
| Erithizon, Cunning Giant, Midnight Crusader Shuttle, Trepanation Blade | one odd defending-player clause each | see `parser_probe blocked 'defending player'` |

### Unsupported Rooms (reference only; not actionable queue entries)

These explain the remaining Room coverage denominator and must not be treated as implementation work: `Crude Abattoir // Unsavory Kitchen`, `Solitary Study // Endless Corridor`. Both return `NEVER_SUPPORTED` because their Alchemy halves are a permanent non-goal.
