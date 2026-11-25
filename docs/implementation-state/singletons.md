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
| Boneyard Desecrator; Thallid Omnivore; Explosive Singularity; Burn at the Stake | tallies over a sacrifice/tap paid as a cost | The `mark_event_log` window opens at resolution, after costs. |
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

### Pay-or-sacrifice residue (PAR-316 close, PARSER_VERSION 938)

| Card | Gap | Notes |
| --- | --- | --- |
| Stromgald Spy | defending player plays with their hand revealed for as long as ~ remains on the battlefield | no duration-bound hand-reveal primitive |
| Pygmy Hippo | drain the defending player's mana abilities and add the mana later as a delayed effect | one-off mana redirection |
| Dark Deal | each player discards their hand, then draws that many cards minus one | the PAR-316 wheel (`then_draw_hand_size`) has no offset |

### Defending-player chooser residue (PAR-317 close, PARSER_VERSION 939)

| Card | Gap | Notes |
| --- | --- | --- |
| The Seventh Doctor | defending player guesses a mana value; cast the card free if wrong | guess primitive plus free cast |
| Celestine Cave Witch | curse the defending player | no curse-a-player primitive |
| Witch-king of Angmar | each opponent who was dealt combat damage by it sacrifices a creature that dealt combat damage to you; the Ring tempts you | damage-history filter on the edict |
| Drana, the Last Bloodchief | defending player chooses a nonlegendary creature card in your graveyard; return it with a +1/+1 counter | opponent chooses from the controller's graveyard |
| Labyrinth Raptor | a creature defending player controls that's blocking it | blocker-relative selection |

### Defending-player count residue (PAR-318 close, PARSER_VERSION 940)

| Card | Gap | Notes |
| --- | --- | --- |
| Snowblind | enchanted creature gets -X/-Y, X = snow lands its controller (or defending player, while attacking) controls, Y = min(X, toughness - 1) | one-off clamp and role-dependent count |
| Awesome Presence | enchanted creature can't be blocked unless the blocker's controller pays {N} for each | `block_tax` is per blocker globally, not per attacker |
| Robber of the Rich | cast an exiled card during any turn you attacked with a Rogue | turn-history-gated cast-from-exile permission |
| Bursting Beebles | can't be blocked as long as defending player controls a permanent that shares an artist with it | `Card` carries no `artist` (printing metadata, not a rules characteristic) |
| Must Be Knights | counts "Enchanting Tale" cards (set code WOT) | many WOT printings share names with WOE originals; the oracle cache cannot tell them apart |

### Modal wrapper residue (PAR-310 close, PARSER_VERSION 941)

| Card | Gap | Notes |
| --- | --- | --- |
| Immard, the Stormcleaver | put a charge counter on it or remove one from it; "when you remove a counter this way, choose one —" | put-or-remove counter choice plus a reflexive trigger keyed on which was chosen |

### Normalization residue (PAR-311 close, PARSER_VERSION 943)

The names now fold correctly; what still blocks each card is a different clause.

| Card | Open clause |
| --- | --- |
| Destroy the Evidence | its controller reveals cards until a land |
| Fear Fire Foes! | damage can't be prevented this turn |
| Call Damage Control, Fruitcake Elemental, Fetching Garden, B.F.M., Water Gun Balloon Game, Segovian Sword, Yet Another Night in Vegas, "Ach! Hans, Run!" | one-off or Un-set text the scan grouped under normalization |

### Amount residue (PAR-284 milestone 16, PARSER_VERSION 961)

One-off amount phrases from the v961 `P1-B Mengen` scan, each checked with `parser_probe.py blocked`; four are 2-card pairs below the ticket threshold (Springjack Shepherd / Phosphorescent Feast, Baleful Stare / Withering Gaze, Kaima / Havoc Eater, In the Eye of Chaos / Invoke Prejudice).

| Card | Gap | Notes |
| --- | --- | --- |
| Balduvian Fallen | `whenever ~'s cumulative upkeep is paid, it gets +1/+0 until end of turn for each {b} or {r} spent this way.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Doran, Besieged by Time | `whenever a creature you control attacks or blocks, it gets +x/+x until end of turn, where x is the difference between its power and toughness.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: its cost-reduction static. |
| Dovescape | `that player creates x 1/1 white and blue bird creature tokens with flying, where x is the spell's mana value.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: third-person subject guard. |
| One with the Kami | `whenever enchanted creature or another modified creature you control dies, create x 1/1 colorless spirit creature tokens, where x is that creature's power.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: union head `enchanted creature or another modified creature`. |
| Heart of Bogardan | `when a player doesn't pay ~'s cumulative upkeep, ~ deals x damage to target player or planeswalker and each creature that player or that planeswalker's controller controls, where x is twice the number of age counters on ~ minus 2.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Immortal Coil | `exile a card from your graveyard for each 1 damage prevented this way.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Havoc Eater | `put x +1/+1 counters on ~, where x is the total power of creatures goaded this way.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Kaima, the Fractured Calm | `put a +1/+1 counter on ~ for each creature goaded this way.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| The Master of Lake-town | `when ~ dies, draw a card for each graveyard with 7 or more cards in it.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card and its named sibling. Sibling: Master's Councillors (same count phrase, P2 Friedhof), 2 cards. |
| Springjack Shepherd | `when ~ enters, create a 0/1 white goat creature token for each white mana symbol in the mana costs of permanents you control.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Phosphorescent Feast | `you gain 2 life for each green mana symbol in those cards' mana costs.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Baleful Stare | `you draw a card for each mountain and red card in it.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Withering Gaze | `you draw a card for each forest and green card in it.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Power Surge | `at the beginning of each player's upkeep, ~ deals x damage to that player, where x is the number of untapped lands they controlled at the beginning of this turn.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Slime Against Humanity | `put x +1/+1 counters on it, where x is 2 plus the total number of cards you own in exile and in your graveyard that are oozes or are named ~.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Staff of Eden, Vault's Key | `{t}: draw a card for each permanent you control but don't own.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: graveyard-to-battlefield ETB. |
| Stinging Study | `you draw x cards and you lose x life, where x is the mana value of a commander you own on the battlefield or in the command zone.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| Strength of the Tajuru | `choose target creature, then choose another target creature for each time this spell was kicked.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card and its named sibling. Sibling: Comet Storm (same multi-target-per-kick phrase), 2 cards. |
| The Celestial Toymaker | `at the beginning of each end step, each opponent loses 2 life for each spell or ability that caused 1 or more players to guess or to group cards or permanents into a pile this turn.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: pile-split attack trigger. |
| Volo, Itinerant Scholar | `{2}, {t}: draw a card for each creature type noted for target permanent you control named ~'s journal.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Also blocked: the journal token's noting trigger. |
| Zenith Flare | `~ deals x damage to any target and you gain x life, where x is the number of cards with a cycling ability in your graveyard.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. |
| In the Eye of Chaos | `whenever a player casts an instant spell, counter it unless that player pays {x}, where x is its mana value.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Pair with Invoke Prejudice (same unless-pays-its-mana-value counter). |
| Invoke Prejudice | `whenever an opponent casts a creature spell that doesn't share a color with a creature you control, counter that spell unless that player pays {x}, where x is its mana value.` | PAR-284 closure (v961): `parser_probe.py blocked` on this clause lists only this card. Pair with In the Eye of Chaos. |

### Amount residue (PAR-284 close, PARSER_VERSION 968)

Cards still open when PAR-284 closed, each re-checked against the pool; no sibling shares the missing primitive. Pairs worth taking together: Blazing Effigy / Impact Resonance, Auntie Ant / Mutated Cultist, Song of Blood / The Eagles Are Coming!.

| Card | Gap | Notes |
| --- | --- | --- |
| Sudden Salvation | `choose up to 3 target permanent cards in graveyards that were put there from the battlefield this turn. ... you draw a card for each opponent who controls 1 or more of those permanents.` | PAR-284 close (v968): the target filter (graveyard arrival from the battlefield this turn) and a count over the chosen set's controllers (referent set) are both missing. |
| Pact of the Serpent | `choose a creature type. target player draws x cards and loses x life, where x is the number of creatures they control of the chosen type.` | PAR-284 close (v968): the chosen-type tail after `they control` is not in `_RELATIVE_PLAYER_COUNT_RE`, and a "choose a creature type" producer is not a `choose_targets` referent. 19 cards print `of the chosen type`, so check the chosen-type count family before hand-authoring. |
| Vren, the Relentless | `create x 1/1 black Rat tokens with "~ gets +1/+1 for each other Rat you control", where x is the number of creatures that were exiled under your opponents' control this turn.` | PAR-284 close (v968): no history verb for exile with a controller scope (LEAVES_BATTLEFIELD to exile), plus the token's quoted anthem. |
| Reap | `return up to x target cards from your graveyard to your hand, where x is the number of black permanents target opponent controls as you cast this spell.` | PAR-284 close (v968): the count reads another target of the same cast; `targeting.resolved_count` needs the earlier picks passed in and a two-step announcement in the cast UI / legal actions. |
| Blazing Effigy | `when ~ dies, it deals x damage to target creature, where x is 3 plus the amount of damage dealt to ~ this turn by other sources named ~.` | PAR-284 close (v968): a named-source qualifier on the `DAMAGE` tally (`history_phrase.parse_damage_taken_count` groups sources by card type only). Pair with Impact Resonance. |
| Impact Resonance | `~ deals x damage divided as you choose among any number of target creatures, where x is the greatest amount of damage dealt by a source to a permanent or player this turn.` | PAR-284 close (v968): a max over per-source sums of `DAMAGE` events (an aggregate variant of `event_count`), plus an announce-time divided total (M22 machinery). Pair with Blazing Effigy. |
| Anowon, the Ruin Thief | `whenever 1 or more rogues you control deal combat damage to a player, that player mills a card for each 1 damage dealt to them. if the player mills at least 1 creature card this way, you draw a card.` | PAR-284 close (v968): the per-event damage payload under a group batch trigger, then a milled-type condition. |
| Auntie Ant, Ant Auntie | `for each creature you control, you may remove a counter from it. create a 1/1 green Insect token for each counter removed this way.` | PAR-284 close (v968): effect-side counter removal tally (`counters_removed_this_way`) in a per-creature loop; also `when ~ enters, multiblight 4`. Pair with Mutated Cultist. |
| Mutated Cultist | `when you cast this spell, remove all counters from up to 1 target permanent or opponent. the next spell you cast this turn costs {1} less to cast for each counter removed this way.` | PAR-284 close (v968): the same effect-side removal tally, plus a "next spell" cost reduction that carries it. Pair with Auntie Ant. |
| Emergent Sequence | `search your library for a basic land card, put it onto the battlefield tapped, then shuffle. that land becomes a 0/0 green and blue Fractal creature that's still a land. put a +1/+1 counter on it for each land you had enter the battlefield under your control this turn.` | PAR-284 close (v968): the count is a plain `history_phrase` row; the open part is the animation with no duration (`becomes a 0/0 ... that's still a land`). |
| Niko Aris | `+1: up to 1 target creature you control can't be blocked this turn. whenever that creature deals damage this turn, return it to its owner's hand.` and `-1: ~ deals 2 damage to target tapped creature for each card you've drawn this turn.` | PAR-284 close (v968): shard tokens, an effect-created trigger on the chosen creature and the tapped-creature damage per card drawn are all open; the draw count itself is a `history_phrase` row. |
| Razorfield Ripper | `whenever ~ or equipped creature attacks, you get {e}, then it gets +x/+x until end of turn, where x is the amount of {e} you have.` | PAR-284 close (v968): the amount parses (`energy_counters_you_have`); the pronoun host of the `~ or equipped creature` head is unresolved. |
| Sword of War and Peace | `whenever equipped creature deals combat damage to a player, ~ deals damage to that player equal to the number of cards in their hand and you gain 1 life for each card in your hand.` | PAR-284 close (v968): the amount parses with `of: event_player` but `event_player_events` carries only STEP_BEGIN, so the gate refuses. The v968 `damaged_player` + `["DAMAGE"]` marker (Hoard Hauler) is the model, but the body's recipient selector must be checked first. |
| Song of Blood | `mill 4 cards. whenever a creature attacks this turn, it gets +1/+0 until end of turn for each creature card put into your graveyard this way.` | PAR-284 close (v968): the payoff sits in an effect-created trigger, so the milled tally must be frozen into it when the spell resolves. Pair with The Eagles Are Coming!. |
| The Eagles Are Coming! | `... return each chosen creature to your hand. at the beginning of the next upkeep, create a 4/4 white Bird Soldier token with flying for each creature returned to your hand this way.` | PAR-284 close (v968): the same frozen `returned this way` tally inside a delayed trigger, plus `if kicked, instead choose any number of target creatures you own`. Pair with Song of Blood. |
| Lukka, Bound to Ruin | `-4: ~ deals x damage divided as you choose among any number of target creatures and/or planeswalkers, where x is the greatest power among creatures you control as you activate this ability.` | PAR-284 close (v968): needs the M22 announce-time total for an activated (loyalty) ability; the `+1: add {R}{G}. Spend this mana only to cast creature spells or activate abilities of creatures` line is a second blocker. |
| Chong and Lily, Nomads | `whenever 1 or more Bards you control attack, choose 1 - put a lore counter on each of any number of target Sagas you control; creatures you control get +1/+0 until end of turn for each lore counter among Sagas you control.` | PAR-284 close (v968): the amount parses; the Bard batch attack head, `any number of target Sagas` counter placement and the modal header are open. |
| Rose Tyler | `whenever ~ attacks, put a time counter on it for each suspended card you own and each other permanent you control with a time counter on it.` | PAR-284 close (v968): the engine has no suspend state to count (RULE 702.62; `grep suspend` finds unrelated suspends). 84 cached cards print Suspend / `suspended`, 29 are UNMODELED, so a Suspend mechanic ticket may be worth opening on its own merits. |
| Hurska Sweet-Tooth | `whenever hurska attacks, create a food token.` | PAR-284 close (v968): the normalizer does not fold the legendary's given name `Hurska` (no comma, no "the") to `~`; the amount (`the amount of life you gained`) already parses. |
| Monstrous Onslaught | hand-authored entry measures the damage total at resolution | PAR-284 close (v968): the parser now yields the announce-time total (M22, `announced_amount`) for the same text. Retire the hand entry and re-run its tests. |
| Phyrexian Unlife | `as long as you have 0 or less life, all damage is dealt to you as though its source had infect.` | The `you don't lose the game for having 0 or less life` line parses since v968 (`cant_lose_game`, `reason: life`); the infect-conditional damage line is open. |
| Soul Echo | `... target opponent may choose that for each 1 damage that would be dealt to you until your next upkeep, you remove an echo counter from this enchantment instead.` | The life exemption parses since v968; the enters-with-X-counters / sacrifice-if-none / opponent-chosen damage replacement is open. |
| Pact Weapon | `whenever equipped creature attacks, draw a card and reveal it. the creature gets +x/+x until end of turn and you lose x life, where x is that card's mana value.` | The gated life exemption (`as long as ~ is attached to a creature`) parses since v968; the reveal-then-pump trigger and `Equip - discard a card` are open. |
| Marina Vendrell's Grimoire | `you have no maximum hand size and don't lose the game for having 0 or less life.` then `whenever you lose life, discard that many cards. then if you have no cards in hand, you lose the game.` | The combined sentence is not split by the new row (only the bare sentence is read); the discard-that-many trigger is open. |
| Gerrard and Hanna | `whenever ~ attacks, you gain 1 life for each card in target opponent's hand. then, choose 1 —` | PAR-284 close (v968, from PAR-310): the hand-count amount parses elsewhere; the lead effect before a chosen mode (`modes["lead_effects"]` prepended in `_resume_trigger_mode`) is missing. |

### Object-filter residue (PAR-285 close, PARSER_VERSION 986)

Re-checked with `parser_probe.py blocked` during the PAR-285 closure scan; paired rows share a shape but stay under 3 cards.

| Card | Gap | Notes |
| --- | --- | --- |
| Abyssal Harvester | `{t}: exile target creature card from a graveyard that was put there this turn` | Per-turn graveyard-arrival record on the pick, then a nightmare-token copy rider. |
| Arcbound Overseer | `put a +1/+1 counter on each creature you control with modular` | Keyword-quality mass group; modular is not in the group-filter keyword set. |
| Biomantic Mastery | `draw a card for each creature target player controls, then draw a card for each creature another target player controls` | Two player targets, per-target creature count. |
| Bioshift; Simic Guildmage | `move ... +1/+1 counter(s) from target creature onto another target creature with the same controller` | Cross-target "same controller" constraint on a counter move. |
| Culling Scales; Topple | `destroy / exile target ... permanent / creature with the lowest mana value / the greatest power among creatures on the battlefield` | Superlative target filter (no live-extremum target kind). |
| Desecrate Reality; Sylvan Primordial | `for each opponent, exile up to 1 / destroy target <qualified> permanent that player controls` | Per-opponent round plus a parity (even mana value) or noncreature quality; Desecrate Reality also has an odd-mana-value graveyard return. |
| Display of Dominance | `destroy target blue or black noncreature permanent` | Colour union combined with a noncreature negation on a permanent target; second mode is a can't-be-targeted-by-colour restriction. |
| Eaten by Spiders | `destroy target creature with flying and all equipment attached to that creature` | Attached-Equipment rider on a keyword-quality target. |
| Ent-Draught Basin | `{x}, {t}: put a +1/+1 counter on target creature with power x` | Target stat equal to the announced X (the stat-bound slot has bounds, not equality to X). |
| Everythingamajig; Urza's Hot Tub | `search your library for a card that shares a complete word in its name with the discarded card` | Word-in-name referent for a library search criterion. |
| Gallia, Tragic Host; Winter Soldier, Icy Assassin | `return this card from your graveyard to the battlefield [tapped] with a +1/+1 / finality counter on her / him` | Self-return from graveyard with an entry counter; Gallia's cost exiles another creature card from the graveyard, Winter Soldier also attaches an Equipment. |
| Iron Man, Armored Avenger; Tori D'Avenant, Fury Rider | `other attacking modified creatures gain flying` / `other red attacking creatures you control gain trample` | "other" + attacking + quality group subject for a keyword grant (the v984 slot covers "attacking <quality> creatures you control", not "other"). |
| Krovikan Horror | `if this card is in your graveyard with a creature card directly above it` | Graveyard-order intervening-if. |
| Lulu, Loyal Hollyphant | `if a permanent you controlled left the battlefield this turn, put a +1/+1 counter on each tapped creature you control, then untap them` | Leave-battlefield-this-turn record plus tapped-group counter-then-untap. |
| Merfolk Assassin | `{t}: destroy target creature with islandwalk` | Landwalk keyword quality on a target. |
| Rampaging Yao Guai | `destroy any number of target artifacts and/or enchantments with total mana value x or less` | Aggregate mana-value bound across a target set. |
| Ravager Wurm | `destroy target land with an activated ability that isn't a mana ability` | Ability-quality filter; the ETB is also a choose-one with a fight mode. |
| Scavenger's Talent | `you may sacrifice 3 other nonland permanents. if you do, return a creature card from your graveyard to the battlefield with a finality counter on it` | Counted qualified sacrifice as a reflexive "if you do" antecedent plus a finality-counter reanimation. |
| Shadows' Verdict | `exile all creatures and planeswalkers with mana value 3 or less from the battlefield and all creature and planeswalker cards with mana value 3 or less from all graveyards` | Two-zone mass exile with a shared mana-value bound. |
| Sorin, Lord of Innistrad | `-6: destroy up to 3 target creatures and/or other planeswalkers` | Mixed creature / other-planeswalker multi-target plus a return-each-put-this-way rider. |
| Spelltwine | `exile target instant or sorcery card from your graveyard and target instant or sorcery card from an opponent's graveyard` | Two graveyard picks of different scope, then copy and free cast. |
| Thraben Exorcism | `exile target spirit, creature with disturb, or enchantment` | Three-way union mixing a subtype, a keyword quality and a type. |
| Trick Shot | `6 damage to target creature and 2 damage to up to 1 other target creature token` | Second target qualified as a token with "other". |
| Ugin, the Spirit Dragon | `-x: exile each permanent with mana value x or less that's 1 or more colors` | Mass group with an X mana-value bound plus a "1 or more colors" quality. |
| Whip Vine | `{t}: tap target creature with flying blocked by ~` | Blocked-by-source quality; the lock-while-tapped rider is a separate duration. |
| Éowyn, Fearless Knight | `exile target creature an opponent controls with greater power` | Target power compared with the source's power (the stat-bound slot has a numeric bound or a measured count, not the source stat); the pump rider reads the exiled creature's colours. |
| Dire Downdraft | `this spell costs {1} less to cast if it targets an attacking or tapped creature` | Cost reduction conditioned on the chosen target's state. |
| Ivorytusk Fortress | `untap each creature you control with a +1/+1 counter on it during each other player's untap step` | Extra untap in the other players' untap steps over a counter-quality group. |
| Primevals' Glorious Rebirth | `return all legendary permanent cards from your graveyard to the battlefield` | Mass graveyard return with a supertype-plus-"permanent card" filter. |
| Sol, Advocate Eternal | `legendary partner` (+ `support 4 and investigate 4 times` after attacking or blocking with its partner) | Partner variant without a name list; the paired attack/block head is separate. |
| Spy Eye | `you may draw a card from that player's library` | Draw from another player's library. |
| Stiltzkin, Moogle Merchant | `target opponent gains control of another target permanent you control. if they do, you draw a card` | Give-control-of-your-own-permanent with an if-they-do rider. |
| The Book of Vile Darkness | `exile ~ and artifacts you control named eye of vecna and hand of vecna: create vecna ... with all triggered abilities of the exiled cards` | Named-artifact cost plus a token inheriting the exiled cards' abilities. |
| Wing Puncture | `target creature you control deals damage equal to its power to target creature with flying` | One-sided bite with a keyword-quality second target. |
| Wing Storm | `deals damage to each player equal to twice the number of creatures that player controls with flying` | Per-player doubled count of a keyword-quality group. |
| Apocalypse Chime | `destroy all nontoken permanents with a name originally printed in the homelands expansion` | Printed-set filter; no other card filters by original expansion. |
| Primal Empathy | `draw a card if you control a creature with the greatest power among creatures on the battlefield` | Superlative-power condition at upkeep (sibling shape of the Culling Scales / Topple target row). |
| Fluttershy | `put a +1/+1 counter on each creature with a tail target player controls` / `stare down` | Joke qualities on a Secret Lair card (not set_type funny, so not auto-parked); likely park rather than author. |

### Trigger- and cost-head residue (PAR-286 close, PARSER_VERSION 997)

P1-D solo cards at v997 without a shared shape of 3+, plus the heads the PAR-286 line named. Missing engine primitives moved to MEC-151–155; Emrakul's Evangel moved to MEC-169 (MEC-145 close).

| Card | Gap | Notes |
| --- | --- | --- |
| Arnyn, Deathbloom Botanist | `whenever a creature you control with power or toughness 1 or less dies, target opponent loses 2 life and you gain 2 life.` | dies head with a 'power or toughness 1 or less' creature filter |
| Autarch Mammoth | `when ~ enters and whenever it attacks while saddled, create a 3/3 green elephant creature token.` | compound head 'when ~ enters and whenever it attacks while saddled' (per-event gate on one head) |
| Brotherhood Scribe | `whenever you get 1 or more {e} during your turn, creatures you control get +1/+1 until end of turn.` | 'whenever you get 1 or more {E} during your turn' (energy-gain head with turn gate) |
| Chandra's Phoenix | `whenever an opponent is dealt damage by a red instant or sorcery spell you control or by a red planeswalker you control, return this card from your graveyard to your hand.` | 'whenever an opponent is dealt damage by a red instant or sorcery spell you control or by a red planeswalker you control' (damage head with a colour-qualified source union) + return from graveyard |
| Chandra's Regulator | `{1}, {t}, discard a mountain card or a red card: draw a card.` | cost 'discard a Mountain card or a red card' (union cost filter) |
| Circle of Confinement | `whenever an opponent casts a vampire spell with the same name as a card exiled with ~, you gain 2 life.` | 'whenever an opponent casts a Vampire spell with the same name as a card exiled with ~' (linked-exile name filter on a cast head) |
| Coffin Queen | `when ~ becomes untapped or you lose control of ~, exile that creature.` | 'when ~ becomes untapped or you lose control of ~, exile that creature' (linked creature + untap/control-loss head) |
| Corruption of Towashi | `whenever a permanent you control transforms or a permanent you control enters transformed, you may draw a card.` | 'whenever a permanent you control transforms or enters transformed' (union with an enters-transformed event) |
| Devouring Tendrils | `when the permanent you don't control dies this turn, you gain 2 life.` | 'when the permanent you don't control dies this turn' (linked 2nd-target referent after a bite; no `that creature` wording) |
| Donna Noble | `whenever ~ or a creature it's paired with is dealt damage, ~ deals that much damage to target opponent.` | 'whenever ~ or a creature it's paired with is dealt damage, deals that much damage' (soulbond pair subject) |
| Edea, Possessed Sorceress | `whenever a creature you control but don't own dies, return it to the battlefield under its owner's control and you draw a card.` | 'a creature you control but don't own dies, return it under its owner's control' (owner-vs-controller subject) |
| Elektra, Femme Fatale | `when you do, it deals 4 damage to target creature.` | reflexive 'when you do, it deals 4 damage to target creature' (payoff names the cost object) |
| Flesh Reaver | `whenever ~ deals damage to a creature or opponent, ~ deals that much damage to you.` | 'whenever ~ deals damage to a creature or opponent, ~ deals that much damage to you' (damage amount echo) |
| Foul Emissary | `when you sacrifice ~ while casting a spell with emerge, create a 3/2 colorless eldrazi horror creature token.` | 'when you sacrifice ~ while casting a spell with emerge' (emerge-cost sacrifice head) |
| Hibernation's End | `whenever you pay ~'s cumulative upkeep, you may search your library for a creature card with mana value equal to the number of age counters on ~, put it onto the battlefield, then shuffle.` | 'whenever you pay ~'s cumulative upkeep' (cumulative-upkeep payment event) |
| Inferno of the Star Mounts | `when its power becomes 20 this way, it deals 20 damage to any target.` | 'when its power becomes 20 this way' (state-threshold reflexive) |
| Ivora, Insatiable Heir | `when ~ enters and whenever it deals combat damage to a player, create a blood token.` | compound head 'when ~ enters and whenever it deals combat damage to a player' (compound heads) |
| Jaws, Relentless Predator | `whenever a noncreature artifact is sacrificed or destroyed, ~ deals 1 damage to each opponent.` | 'whenever a noncreature artifact is sacrificed or destroyed' (sacrificed-or-destroyed union event) |
| Justice, Vance Astrovik | `whenever another nonland permanent you control is returned to its owner's hand, put a +1/+1 counter on ~.` | 'whenever another nonland permanent you control is returned to its owner's hand' (bounce event head) |
| Key to the Side-Door | `{1}, {t}, discard a legendary card with the same name as a legendary permanent you control: draw 2 cards.` | cost 'discard a legendary card with the same name as a legendary permanent you control' (relational cost filter) |
| Kraven the Hunter | `whenever a creature an opponent controls with the greatest power among creatures that player controls dies, draw a card and put a +1/+1 counter on ~.` | 'whenever a creature an opponent controls with the greatest power among creatures that player controls dies' (relative-greatest filter) |
| Krumar Initiate | `{x}{b}, {t}, pay x life: ~ endures x.` | cost '{X}{B}, {T}, pay X life' then '~ endures X' (X life cost feeding endure) |
| Lady Octopus, Inspired Inventor | `whenever you draw your first or second card each turn, put an ingenuity counter on ~.` | 'whenever you draw your first or second card each turn' (ordinal draw-count head) |
| Lo and Li, Royal Advisors | `whenever an opponent discards a card or mills 1 or more cards, put a +1/+1 counter on each advisor you control.` | 'whenever an opponent discards a card or mills 1 or more cards' (discard-or-mill union) |
| Loot Dispute | `whenever you attack the player who has the initiative, create a treasure token.` | 'whenever you attack the player who has the initiative' (initiative-holder defender; initiative exists in engine) |
| Market Gnome | `when ~ is exiled from the battlefield while you're activating a craft ability, you gain 1 life and draw a card.` | 'when ~ is exiled from the battlefield while you're activating a craft ability' (craft-cost exile head; craft is an engine word) |
| Master Symmetrist | `whenever a creature you control with power equal to its toughness attacks, it gains trample until end of turn.` | 'whenever a creature you control with power equal to its toughness attacks' (self-relational creature filter) |
| Mikey & Leo, Chaos & Order | `whenever you put a counter on a creature you control, draw a card.` | 'whenever you put a counter on a creature you control' (any-counter event head) |
| Mistbind Clique | `when a faerie is championed with ~, tap all lands target player controls.` | 'when a Faerie is championed with ~' (champion linkage) |
| Mob Mentality | `whenever all non-wall creatures you control attack, enchanted creature gets +x/+0 until end of turn, where x is the number of attacking creatures.` | 'whenever all non-Wall creatures you control attack' (all-attack head) + enchanted-creature pump with X = attackers |
| Ms. Marvel, Elastic Ally | `whenever a creature you control with power greater than its base power deals combat damage to a player, draw a card.` | 'a creature you control with power greater than its base power deals combat damage' (base-power comparison filter) |
| Namor the Sub-Mariner | `whenever you cast a noncreature spell with 1 or more blue mana symbols in its mana cost, create that many 1/1 blue merfolk creature tokens.` | 'whenever you cast a noncreature spell with 1 or more blue mana symbols in its mana cost, create that many tokens' (mana-symbol-count cast head; 6 pool cards share the family, 2 unclaimed) |
| Ob Nixilis, Unshackled | `whenever an opponent searches their library, that player sacrifices a creature of their choice and loses 10 life.` | 'whenever an opponent searches their library' (search event head) |
| Powerleech | `whenever an artifact an opponent controls becomes tapped or an opponent activates an artifact's ability without {t} in its activation cost, you gain 1 life.` | 'whenever an artifact an opponent controls becomes tapped or an opponent activates an artifact's ability without {T}' (compound) |
| Preacher of the Schism | `whenever ~ attacks while you have the most life or are tied for most life, you draw a card and you lose 1 life.` | 'whenever ~ attacks while you have the most life or are tied for most life' (attack head with a life-rank gate) |
| Psychic Pickpocket | `when it connives this way, return up to 1 target nonland permanent to its owner's hand.` | 'when it connives this way' (reflexive on connive; CONNIVES event exists) |
| Psychogenic Probe | `whenever a spell or ability causes a player to shuffle their library, ~ deals 2 damage to that player.` | 'whenever a spell or ability causes a player to shuffle their library' (shuffle-cause head; SHUFFLE event exists) |
| Rage Extractor | `whenever you cast a spell with {h} in its mana cost, ~ deals damage equal to that spell's mana value to any target.` | 'whenever you cast a spell with {H} in its mana cost, ~ deals damage equal to that spell's mana value' (mana-cost symbol cast head, with the spell's mana value) |
| Selfless Squire | `whenever damage that would be dealt to you is prevented, put that many +1/+1 counters on ~.` | 'whenever damage that would be dealt to you is prevented, put that many counters' (prevention event, amount carry) |
| Skyfire Phoenix | `when you cast your commander, return this card from your graveyard to the battlefield.` | 'when you cast your commander, return this card from your graveyard to the battlefield' (commander-cast head from the graveyard) |
| Spare Changeling | `whenever you pay an additional cost while casting a spell, you may return this card from your graveyard to your hand.` | 'whenever you pay an additional cost while casting a spell' (additional-cost-paid event; head absent) + return from graveyard |
| Storm Cauldron | `whenever a land is tapped for mana, return it to its owner's hand.` | 'whenever a land is tapped for mana, return it to its owner's hand' (any land tapped-for-mana head with a pronoun body) + replacement rider |
| Strict Proctor | `whenever a permanent entering causes a triggered ability to trigger, counter that ability unless its controller pays {2}.` | 'whenever a permanent entering causes a triggered ability to trigger, counter that ability unless its controller pays {2}' (trigger-caused-by-ETB head) |
| Surrak, Elusive Hunter | `whenever a creature you control or a creature spell you control becomes the target of a spell or ability an opponent controls, draw a card.` | 'whenever a creature you control or a creature spell you control becomes the target of a spell or ability an opponent controls' (target-event union) |
| The Beast, Deathless Prince | `whenever a creature deals combat damage to its owner, untap ~ and draw a card.` | 'whenever a creature deals combat damage to its owner' (owner-vs-damaged-player relation) |
| The Council of Four | `whenever a player draws their second card during their turn, you draw a card.`; `whenever a player casts their second spell during their turn, you create a 2/2 white knight creature token.` | 'whenever a player draws their second card / casts their second spell during their turn' (ordinal per-player heads; two lines) |
| The Master, Mesmerist | `whenever a creature with skulk deals combat damage to 1 of your opponents, put a +1/+1 counter on ~ and draw a card.` | 'whenever a creature with skulk deals combat damage to 1 of your opponents' (batch keyword-subject combat damage) |
| Timestream Navigator | `{2}{u}{u}, {t}, put ~ on the bottom of its owner's library: take an extra turn after this 1.` | cost 'put ~ on the bottom of its owner's library' + 'take an extra turn after this 1' (self-library cost) |
| Tornado | `{2}{g}, pay 3 life for each velocity counter on ~: destroy target permanent and put a velocity counter on ~.` | cost 'pay 3 life for each velocity counter on ~' (counter-scaled life cost) |
| Uchbenbak, the Great Mistake | `descend 8 — {4}{u}{b}: return this card from your graveyard to the battlefield with a finality counter on it.` | 'descend 8 — {4}{U}{B}: return this card from your graveyard to the battlefield with a finality counter' (descend activation gate from the graveyard) |
| Vengeful Pharaoh | `whenever combat damage is dealt to you or a planeswalker you control, if this card is in your graveyard, destroy target attacking creature, then put this card on top of your library.` | 'whenever combat damage is dealt to you or a planeswalker you control, if this card is in your graveyard, destroy target attacking creature, then put this card on top of your library' (graveyard-active trigger) |
| Voldaren Bloodcaster // Bloodbat Summoner | `whenever you create a blood token, if you control 5 or more blood tokens, transform ~.` | 'whenever you create a Blood token, if you control 5 or more Blood tokens, transform ~' (token-created head) |
| Voltaic Visionary // Volt-Charged Berserker | `when you play a card exiled with ~, transform ~.` | 'when you play a card exiled with ~, transform ~' (linked-exile play event) |
| Warped Devotion | `whenever a permanent is returned to a player's hand, that player discards a card.` | 'whenever a permanent is returned to a player's hand, that player discards a card' (bounce head, owner-as-actor) |
| Watcher of Hours | `whenever you remove a time counter from this card while it's exiled, surveil 1.` | 'whenever you remove a time counter from this card while it's exiled, surveil 1' (counter-removed head from exile) |
| Xira, the Golden Sting | `when that creature dies, if it has an egg counter on it, draw a card and create a 1/1 black insect creature token with flying.` | 'when that creature dies, if it has an egg counter on it, draw a card and create a Insect' (linked 'that creature' dies head after an attack-trigger target; counter-gated) |
| Zellix, Sanity Flayer | `whenever a player mills 1 or more creature cards, you create a 1/1 black horror creature token.` | 'whenever a player mills 1 or more creature cards' (mill batch head) |
| Zhur-Taa Druid | `whenever you tap ~ for mana, it deals 1 damage to each opponent.` | 'whenever you tap ~ for mana, it deals 1 damage to each opponent' (tapped-for-mana head with a mana-ability trigger) |
| Zidane, Tantalus Thief | `whenever an opponent gains control of a permanent from you, you create a treasure token.` | 'whenever an opponent gains control of a permanent from you' (control-change head) |
| Gempalm Incinerator | `when you cycle this card, you may have it deal X damage ... Goblins`: "you may have it deal" phrasing (head exists; Gempalm Strider is MODELED) | Named in the PAR-286 backlog line or skipped in M11. |
| Thunderous Might | `whenever enchanted creature attacks, it gets +X/+0` (even a fixed +1/+0 is unclaimed: head with pronoun body) | Named in the PAR-286 backlog line or skipped in M11. |
| Sigil of Valor | `whenever equipped creature attacks alone, it gets +1/+1 for each other creature you control` | Named in the PAR-286 backlog line or skipped in M11. |
| Sapphire Charm | mode 1 `target player draws a card at the beginning of the next turn's upkeep` (delayed upkeep, tagged P1-C) + mode 3 phases out | Named in the PAR-286 backlog line or skipped in M11. |
| Lobelia Sackville-Baggins | `exile target creature card from an opponent's graveyard that was put there from the battlefield this turn, then create X Treasure tokens` (graveyard-arrival object filter, tagged P1-C) | Named in the PAR-286 backlog line or skipped in M11. |
| HELIOS One | `pay X {E}` activation cost | Engine cost `PAY_ENERGY_X` exists; parser cost row shared with Chthonian Nightmare and Sphinx of the Revelation (3 pool cards). |
| Chthonian Nightmare | `pay X {E}` activation cost | See HELIOS One. |

### Cross-sentence referent residue (PAR-287 close, PARSER_VERSION 1002)

P1-E solo cards at v1002 without a shared shape of 3+, plus the 1-2-card missing primitives found while building. Clusters of 3+ moved to PAR-321–324; Savage Order and the search shapes of Entish Restoration and The Earth King stay with PAR-292.

| Card | Gap | Notes |
| --- | --- | --- |
| Bag of Holding | "exile that card from your graveyard" after "whenever you discard a card" | the discard event's card is the referent; needs a DISCARD event card reference |
| Consuming Ferocity | "if that creature has 3 or more +1/+0 counters on it, it deals damage equal to its power to its controller, then destroy that creature and it can't be regenerated" | counter-count condition on the target plus a damage-source swap |
| Crash Landing | "~ deals damage to that creature equal to the number of forests you control" | amount measured over lands, target is the earlier flipped-over creature |
| Creepy Doll | "if you win the flip, destroy that creature" | combat-damage trigger target plus coin_won; indestructible-on-flip is hand-authorable |
| Dovin, Architect of Law | "-9: tap all permanents target opponent controls. That player skips their next untap step." | player-scoped skip-untap after a tap group |
| Entish Restoration | "if you control a creature with power 4 or greater, instead search ... up to 3 basic land cards" | conditional-instead on a search (PAR-292 owns the search shape; the instead-condition is this gap) |
| Jaya, Fiery Negotiator | "whenever you attack this turn, ~ deals damage equal to the number of attacking creatures to that creature" | delayed attack trigger carrying the earlier target |
| Kayla's Command | "it gains double strike until end of turn" | a mode that names the creature of a previous mode |
| Kitesail Freebooter | "you choose a noncreature, nonland card from it. Exile that card until ~ leaves the battlefield" | revealed-hand choice and linked exile |
| Loki, God of Lies | "gain control of that creature until end of turn. If it's your turn, untap that creature and it gains haste" | targeted-spell trigger (only a single creature) + gain control |
| Momir Vig, Simic Visionary | "if it's a creature card, put that card into your hand" | revealed-top-card referent for each of two reveals |
| Nurgle's Conscription | "put target creature card from an opponent's graveyard onto the battlefield ... then exile that player's graveyard" | target card's owner as the player of the next sentence |
| Prowling Geistcatcher | "whenever you sacrifice another creature, exile it. If that creature was a token, put a +1/+1 counter on ~" | sacrificed-object referent with token test |
| Puresight Merrow | "you may exile that card" | the mill/reveal card referent |
| Sabotage Strategist | "whenever 1 or more creatures attack you, those creatures get -1/-0 until end of turn" | attacker batch as a group referent |
| Spider-Man Noir | "then surveil X, where X is the number of counters on it" | counters on the referenced object |
| Summons of Saruman | "you may cast an instant or sorcery spell with mana value X or less from among them without paying its mana cost" | cast from "among them" (the exiled cards) with an X bound |
| Sword of Wealth and Power | "you may choose new targets for the copy" | copy of the cast spell with new targets |
| Taunt from the Rampart | "until your next turn, those creatures can't block" | group referent with a next-turn duration |
| The Fall of Kroog | "~ deals 3 damage to that player and 1 damage to each creature they control" | target-opponent referent over a damage and a group |
| Tiller Engine | "untap that land" | the entering land, replacement-or-tap choice |
| Tui and La, Moon and Ocean | "whenever ~ becomes untapped, put a +1/+1 counter on them" | "them" for a two-object source |
| Vraska, the Cutting Glare | "they create a Treasure token" | target-opponent referent after a sacrifice/loyalty step |
| Waltz of Rage | "you may play it until the end of your next turn" | the card exiled by the previous sentence |
| Watchful Radstag | "whenever ~ evolves, create a token that's a copy of it" | evolve trigger plus a copy of the source |
| Kros, Defense Contractor | "whenever you put 1 or more counters on a creature you don't control, tap that creature and goad it. It gains trample until your next turn" | counter-put batch referent on an opponent's creature |
| Abigale, Eloquent First-Year | keyword counters put after "loses all abilities" | `continuous.py` strips keyword counters from an object that has lost all abilities and keeps no layer-6 timestamps (RULE 613.7); engine primitive, 1 card. |
| Laquatus's Champion | leaves-the-battlefield trigger names the enters trigger's target player | no linked ETB-target primitive (RULE 607.2a); shared only with Soul Scourge. |
| Soul Scourge | leaves-the-battlefield trigger names the enters trigger's target player | See Laquatus's Champion. |
| Neko-Te | "doesn't untap ... for as long as ~ remains on the battlefield" | no duration tied to the source staying on the battlefield (RULE 611.2b). |
| Forger's Foundry | spend-to-exile rider on its mana | the rider cannot create a linked exile pool (RULE 607.2a). |

### Small-modifier residue (PAR-288 close, PARSER_VERSION 1003)

P1-F solo cards at v1003 without a shared shape of 3+. Clusters moved to PAR-325, MEC-156 and ENG-65; Storm of Memories moved to PAR-325.

| Card | Gap | Notes |
| --- | --- | --- |
| Calix, Destiny's Hand | `-3: exile target creature or enchantment you don't control until target enchantment you control leaves the battlefield` | PAR-288 close (v1003): the duration is tied to a second target, not to the source (`until_source_leaves` is source-only); solo P1-F. |
| Congregation at Dawn; Insidious Dreams | `search your library for up to <n> / x <type> cards, reveal them, then shuffle and put those cards on top in any order` | PAR-288 close (v1003): search-to-top with an owner-ordered placement; pair, both solo P1-F (Insidious Dreams also needs the discard-X additional cost, which parses). |
| Dispense Justice | `Metalcraft - that player sacrifices two attacking creatures of their choice instead if you control three or more artifacts` | PAR-288 close (v1003): the override sits on its own ability-word line and replaces the previous line's sacrifice; the line segmenter never joins them. Solo. |
| Magus of the Abyss; The Abyss | `at the beginning of each player's upkeep, destroy target nonartifact creature that player controls of their choice` (+ `it can't be regenerated`) | PAR-288 close (v1003): the target is chosen by the affected player (RULE 115.1 chooser), not the controller; the regeneration rider is a second open sentence. Pair. |
| Orcish Farmer | `{T}: target land becomes a Swamp until its controller's next untap step` | PAR-288 close (v1003): a land-type change with a controller-relative expiry (RULE 611.2b); solo P1-F. |
| Soul Sculptor | `{1}{W}, {T}: target creature becomes an enchantment and loses all abilities until a player casts a creature spell` | PAR-288 close (v1003): type change plus "loses all abilities" with a spell-cast expiry event; solo P1-F. |
| Repel Intruders | `create two 1/1 ... if {W} was spent to cast this spell. Counter up to one target creature spell if {U} was spent` | PAR-288 close (v1003): two independent mana-spent gates on one spell, the second on an optional target; solo P1-F. |
| Shaile, Dean of Radiance // Embrose, Dean of Shadow | `{T}: put a +1/+1 counter on each creature that entered the battlefield under your control this turn` | PAR-288 close (v1003): an entered-this-turn group filter on a counter put; solo P1-F. |
| Urdnan, Dromoka Warrior | `target attacking creature with a +1/+1 counter on it gains first strike. If that creature has two or more +1/+1 counters on it, it gains double strike instead` | PAR-288 close (v1003): the `instead` override works (PAR-288 handles the counter gate), but the base target carries a counter qualifier that the pronoun rewrite loses; solo. |
| Veteran Ice Climber | `whenever ~ attacks, up to one target player mills cards equal to ~'s power` | PAR-288 close (v1003): an optional player target on a mill; solo P1-F. |
| Negative Zone Portal | `if you lose the flip, sacrifice ~ and return a card exiled with it at random to its owner's hand` | PAR-288 close (v1003): random pick from the linked exile pile after a coin flip; solo P1-F. Pair with the `P2 Wuerfel und Muenze` coin tallies (PAR-309). |
| Court of Locthwain | `if you're the monarch, until end of turn, you may cast a spell from among cards exiled with ~ without paying its mana cost` | PAR-288 close (v1003): a monarch-gated window leading the sentence ("until end of turn" before "you may"); the exiled-with pool exists. |
| The Ur-Dragon | `whenever 1 or more Dragons you control attack, draw that many cards, then you may put a permanent card from your hand onto the battlefield` | PAR-288 close (v1003): "that many" under the grouped-attack head then an optional hand put; plus the command-zone Dragon cost reduction (PAR-301). |
| Tishana's Tidebinder | `counter up to one target activated or triggered ability. If an ability of an artifact, creature, or planeswalker is countered this way, that permanent loses all abilities for as long as ~ remains on the battlefield` | PAR-288 close (v1003): optional ability target plus the countered-this-way rider; PAR-308 owns the ability-counter family. |
| Jon Irenicus, Shattered One | `target opponent gains control of up to one target creature you control. Untap it. It's goaded for the rest of the game and gains "can't be sacrificed"` | PAR-288 close (v1003): optional creature target for a control gift and a permanent goad; plus a second head (`whenever a creature you own but don't control attacks`). |
| Lagrella, the Magpie | `exile any number of other target creatures controlled by different players until ~ leaves the battlefield` | PAR-288 close (v1003): `any number of` targets with a distinct-controller group constraint; also the `when an exiled card enters under your control this way` head (PAR-303). |
| Intellect Devourer | `each opponent exiles a card from their hand until ~ leaves the battlefield` | PAR-288 close (v1003): each opponent picks from their own hand with a source-leaves return; plus the any-colour cast rider (PAR-299). |

### Continuous-static residue (PAR-289 close, PARSER_VERSION 1007)

| Card | Gap | Notes |
| --- | --- | --- |
| Ekthi, Contaminator Priest | "Each Equipment you control has living weapon": a granted `living_weapon` is a bare slug, the RULE 702.92a trigger is built only for a printed keyword | refused through `UNGRANTABLE_FLAG_KEYWORDS`; see ENG-66 |
| Don Andres, the Renegade | "Each creature you control but don't own gets ..." | needs a "controlled but not owned" filter (RULE 108.3) in `parse_object_phrase` |
| Planar Nexus | "This land is every nonbasic land type" | needs an every-nonbasic-land-type type change (RULE 205.3i) |
| Glittering Frost | "Enchanted land is snow" | supertype addition on the host; the mana rider is a separate clause |
| Nylea's Presence | "Enchanted land is every basic land type in addition to its other types" | host every-basic-land-type addition (RULE 305.7) |
| The Tarrasque | "has haste and ward {10} as long as it was cast" | gated self grant on a was-cast condition |
| Khod, Etlan Shiis Envoy | "Other Homarids, Camarids, Cephalids, Nautilids, and Merfolk you control" | check `CREATURE_SUBTYPES` for Cephalid / Nautilid before blaming the row |
| Spider-Ham, Peter Porker | 18-type ability-word list "Other Spiders, Boars, ... you control get +1/+1" | long coordinated type list after an ability word |
| Rakdos Riteknife | quoted grant "Put a blood counter on Rakdos Riteknife": the folded `~` must stay the Equipment, but a granted ability's self-reference binds to the host | `rows_typed_groups` refuses a quote that puts a counter on `~`; needs a quote-rebind flag |
| Hankyu | same as Rakdos Riteknife (aim counters on the Equipment) | shares the quote-rebind fix |
| Withercrown | "Enchanted creature has base power 0" (power only) plus a quoted upkeep trigger | `rows_typed_groups` has `base_toughness` but no base-power-only clause |

### Restriction residue (PAR-290 close, PARSER_VERSION 1009)

| Card | Gap | Notes |
| --- | --- | --- |
| Lovestruck Beast // Heart's Desire | "can't attack unless you control a 1/1 creature" | condition vocabulary: a creature with exact P/T; the Adventure half is claimed |
| Pipsqueak, Rebel Strongarm | "can't attack alone unless it has a +1/+1 counter on it" | "alone" combined with a counter condition |
| Elephant Grass | "nonblack creatures can't attack you unless their controller pays {2} for each creature they control that's attacking you" | `attack_tax` has an `attacker_filter` param; the row grammar has no filter slot |
| Norn's Annex | "creatures can't attack you or planeswalkers you control unless their controller pays {W/P} for each of those creatures" | Phyrexian-mana tax amount |
| Intimidation Bolt | "other creatures can't attack this turn" | group bar that exempts the damage target (the previous target as an excluded instance) |
| Ember Gale | "creatures target player controls can't block this turn. ~ deals 1 damage to each white and/or blue creature that player controls" | "that player" must name the spell's target player; the group one-shot itself parses |
| Concussive Bolt | "metalcraft: creatures controlled by that player or by that planeswalker's controller can't block this turn" | controller-of-the-target scope plus a metalcraft gate |
| Rumbling Ruin | "count the +1/+1 counters on creatures you control. creatures your opponents control with power less than or equal to that number can't block this turn" | counted threshold carried between sentences |
| Ironclaw Curse | "enchanted creature can't block creatures with power equal to or greater than the enchanted creature's toughness" | filter against the host's toughness (new relative key) |
| Hand to Hand | "during combat, players can't cast instant spells or activate abilities that aren't mana abilities" | combat-gated cast bar plus a gated all-player activation bar |
| Brand of Ill Omen | "enchanted creature's controller can't cast creature spells" | `cast_prohibition` scoped to the host's controller (`player_id` is stamped only at resolution today) |
| Curse of Exhaustion | "enchanted player can't cast more than one spell each turn" | `cast_limit` scoped to the enchanted player |
| Akron Legionnaire | "except for creatures named ~ and artifact creatures, creatures you control can't attack" | exception list in a group attack bar |
| Ensnaring Bridge | "creatures with power greater than the number of cards in your hand can't attack" | dynamic threshold against a hand count |

### Trigger-subject reference residue (ENG-64 close, PARSER_VERSION 1010)

| Card | Gap | Notes |
| --- | --- | --- |
| Dual Nature | "its controller creates a token that's a copy of that creature"; "exile all tokens created with ~" | `copy_permanent` has no creator-is-the-subject's-controller param; tokens carry no created-by-source record (new `GameState` state). Line 2 now carries the trigger-subject reference |
| Legion's End | "... and all other creatures that player controls with the same name as that creature. Then that player reveals their hand and exiles all cards with that name from their hand and graveyard" | controller-scoped name group in `target_group` (shared with Declaration in Stone, Banishment, Deputy of Detention) plus the hand-and-graveyard name exile (shared with Hour of Glory, Deicide) |

### Recorded-referent residue (MEC-145 close, PARSER_VERSION 1018)

Cards the MEC-145 cost / effect referent records reach but that still miss a different, one-card primitive. Clusters went to MEC-146 and MEC-169–172.

| Card | Gap | Notes |
| --- | --- | --- |
| Endemic Plague | `destroy all creatures that share a creature type with the sacrificed creature. they can't be regenerated.` | group filter over the sacrificed creature's creature types (sibling of Sanguine Praetor's `exact_mana_value: sacrificed_cost`) |
| Fatal Grudge | `each opponent chooses a permanent they control that shares a card type with the sacrificed permanent and sacrifices it.` | per-opponent choice filtered by the sacrificed permanent's card types |
| Essence Burn | `~ deals 5 damage to target black or green creature or planeswalker. if that permanent would die this turn, exile it instead.` | the "exile it instead" rider does not arm when the damage sits in a `for_each`; pinned unclaimed in `test_mec145_cost_referents.py` |
| Phyrexian Devourer | `when ~'s power is 7 or greater, sacrifice it.` | state trigger on own power (RULE 603.8); its exile-top-card cost referent already parses |
| Void | `choose a number. destroy all artifacts and creatures with mana value equal to that number. then target player reveals their hand and discards all nonland cards with mana value equal to the number.` | choose-a-number referent for a group filter and a hand discard |
| Public Execution | `destroy target creature an opponent controls. each other creature that player controls gets -2/-0 until end of turn.` | "that player" = the destroyed creature's controller, group pump excluding the target |
| Arcbond | `choose target creature. whenever that creature is dealt damage this turn, it deals that much damage to each other creature and each player.` | delayed trigger on a chosen creature, re-dealing the damage |
| Kogla and Yidaro | `when ~ enters, choose 1 — it gains trample and haste / it fights target creature you don't control; {2}{r}{g}, discard this card: destroy up to 1 target artifact or enchantment. shuffle this card into your library from your graveyard, then draw a card.` | ETB modal plus a hand-activated discard ability that shuffles itself back |

### Attached-host, earlier-target and random-exile residue (PAR-323 to PAR-325 close, PARSER_VERSION 1023–1025)

| Card | Gap | Notes |
| --- | --- | --- |
| Writ of Passage | `whenever enchanted creature attacks, if its power is 2 or less, it can't be blocked this turn.` | `UnblockableEffect` has only a `previous_subject` mode and is not in the binder's attached-host retarget list; pinned unclaimed in `test_par323_attached_host_referents.py`. |
| Obsessive Pursuit | `if x is three or more, ...` after a where-X count of permanents sacrificed this turn (PAR-324 close) | needs a condition on the bound where-X value; the reading must not become `x_paid`. |
| Elkin Lair | `at the beginning of each player's upkeep, that player exiles a card at random from their hand. the player may play that card this turn. at the beginning of the next end step, if the player hasn't played the card, they put it into their graveyard.` (PAR-325 close) | random hand exile by the active player (not the controller) plus a next-end-step delayed graveyard move of the uncast card. |

### Library residue (PAR-292 re-scope, PARSER_VERSION 1054)

Intake from the PAR-292 re-scope: single cards and pairs whose own clause blocks them. Not each re-checked with `parser_probe.py blocked` yet; recheck shared shapes before hand-authoring. Multi-card mechanisms stay on PAR-292; pile cards moved to PAR-298, outside-the-game cards to MEC-144.

| Card | Gap | Notes |
| --- | --- | --- |
| Demonlord Belzenlok | repeat-until loop with a put-into-hand-this-way tally | from the PAR-284 close |
| March of Burgeoning Life | "may exile any number of green cards" additional cost with cost reduction; strict "mana value less than x" on a target | from the PAR-285 close |
| Night Dealings | "put that many theft counters" trigger plus exact "mana value x" fed by a remove-counters cost |  |
| Ringsight | "shares a color with a legendary creature you control" search criterion |  |
| Wild Pair | "same total power and toughness" as the cast creature |  |
| The Earth King | "up to that many" after an attack-count trigger | from the PAR-321 close |
| Savage Order | rider "it gains indestructible until your next turn" on the found card |  |
| Pyre of Heroes | "shares a creature type with the sacrificed creature" plus a mana-value bound |  |
| Light-Paws, Emperor's Voice | "less than or equal to that aura and with a different name than each aura you control" |  |
| Curse of Misfortunes | "doesn't have the same name as a curse attached to enchanted player" |  |
| Instrument of the Bards | "if that card is legendary, create a treasure token" (conditional on the found card) |  |
| Hibernation's End | head "whenever you pay ~'s cumulative upkeep" | body parses |
| Prishe's Wanderings | rider "when you search your library this way, put a +1/+1 counter on target creature you control" |  |
| Dance of the Tumbleweeds | spree modes around the search |  |
| Canoptek Wraith | "you may pay {3} and sacrifice it. If you do, ..." (mana plus self-sacrifice optional cost) | inner choose-then-search is built |
| Arcum Dagsson | "target artifact creature's controller sacrifices it" | search sentence parses |
| Incoming! | "any number of artifact, creature, enchantment, and/or land cards" (one count, four-way type list) |  |
| Collective Voyage | X = total mana paid by each player |  |
| Rootweaver Druid | split control of the found cards |  |
| Scholarship Sponsor | count from a land-count difference |  |
| Settle the Wreckage | "that many" from exiled attackers |  |
| Hazoret's Undying Fury | "exile the top 4 cards" with no "of your library" after the shuffle, plus "lands you control don't untap during your next untap step" | PAR-292 M25; the shuffle lead and cast pool parse |
| Random Encounter | "put each creature card milled this way onto the battlefield" with a haste and end-step return of those cards | PAR-292 M25; the shuffle-then-mill lead parses |
| Unexpected Results | "reveal the top card. If it's a nonland card, you may cast it free. If it's a land card, you may put it onto the battlefield and return ~ to hand" | PAR-292 M25 |
| Metalworker | "{T}: Reveal any number of artifact cards in your hand. Add {C}{C} for each card revealed this way." is a mana ability (RULE 605.1a) whose reveal must be answered during payment; the quality and count parse, fail-closed in `gate._reveal_mana_ability_ok` | PAR-292 M25; needs an interactive choice inside mana payment |
| Sacellum Godspeaker | "reveal any number of creature cards with power 5 or greater from your hand" ("from", not "in") plus a mana ability | PAR-292 M25; the quality parses, only the preposition is open |
| Arsenal Thresher | "as ~ enters, you may reveal any number of other artifact cards from your hand. ~ enters with a +1/+1 counter for each card revealed this way" (replacement) | PAR-292 M25 |
| Kamahl's Summons | "each player may reveal any number of creature cards from their hand. Then each player creates a 2/2 Bear for each card they revealed" | PAR-292 M25; per-player reveal |
| Into the Fire | "put any number of cards from your hand on the bottom of your library, then draw that many cards plus 1" (modal) | PAR-292 M25 |
| Blightwing Bandit | "look at the top card of that player's library, then exile it face down" under "whenever you cast your first spell during each opponent's turn": "that player" is the active player (an opponent), not the caster; the rest parses (M26 face-down window) | PAR-292 M26; needs an `active_player` operand for "that player" under a spell-cast head |
| Wand of Denial | "look at the top card of target player's library. If it's a nonland card, you may pay 2 life. If you do, put it into that player's graveyard" (pay-life rider on the look) | PAR-292 M26 |
| S.N.E.A.K. Dispatcher | "if it has an agents of s.n.e.a.k. watermark, you may reveal it and put it into your hand. Otherwise, put it on your choice of the top or bottom of its owner's library" | PAR-292 M26 |
| Klaw, Master of Sound | "mana of any type can be spent to cast a spell this way" as its own sentence after the play window, plus "whenever you play a card from exile" | PAR-292 M26 |
| Elixir | "shuffle all nonland cards from your graveyard into your library. You gain life equal to the number of cards shuffled into your library this way." (a class filter on the whole graveyard plus a "shuffled this way" count) | PAR-292 M27 |
| Campfire | "put all commanders you own from the command zone and from your graveyard into your hand" (the shuffle sentence parses) | PAR-292 M27 |
| Time Spiral | "you untap up to six lands" (the hand-and-graveyard shuffle and draw parse) | PAR-292 M27 |
| Diminishing Returns | "you exile the top ten cards of your library. Then each player draws up to seven cards" (the shuffle parses) | PAR-292 M27 |
| Glimpse of Tomorrow | "shuffle all permanents you own into your library, then reveal that many cards ... put all non-Aura permanent cards revealed this way onto the battlefield, then do the same for Aura cards" (needs a count from the shuffled set and a two-pass entry) | PAR-292 M27 |
| Etrata, the Silencer | "that player loses the game if they own three or more exiled cards with hit counters on them" (the owner shuffle parses) | PAR-292 M27 |
| Fblthp, Impossibly Lost | trigger head "when one or more of your opponents are dealt combat damage during your turn" (the owner shuffle and the library-empty win parse) | PAR-292 M27 |
| Inferno Hellion | "at the beginning of each end step, if ~ attacked or blocked this turn" (the owner shuffle parses) | PAR-292 M27 |
| Mirror-Mad Phantasm | "if that player does, they reveal cards from the top of that library until a card named ~ is revealed; the player puts that card onto the battlefield and all other cards revealed this way into their graveyard" | PAR-292 M27 |
| Riftsweeper | "choose target face-up exiled card. Its owner shuffles it into their library" (a face-up exile target kind) | PAR-292 M27 |
| This Is How It Ends | "faces a villainous choice: they lose 5 life, or they shuffle another creature they own into their library" | PAR-292 M27 |
| Arachnus Spinner | "put it onto the battlefield attached to target creature" after a multi-zone search (the found card is attached to the ability's own target, which is gone once the search choice resumes) | PAR-292 M28; the zone search, the shuffle tail and the cost parse |
| Say Its Name | cost "exile this card and two other cards named ~ from your graveyard" (the source plus N other same-named cards, only Calim shares "from your graveyard") | PAR-292 M28; the multi-zone search and the sorcery-speed restriction parse |
| The Five Doctors | "if this spell was kicked, put those cards onto the battlefield instead of putting them into your hand" after an "up to five Doctor cards" search | PAR-292 M28; the library-and-graveyard search itself parses |
| The Hunger Tide Rises | chapter IV: "sacrifice any number of creatures. Search ... for a creature card with mana value less than or equal to the number of creatures sacrificed this way" (a count from an unbounded sacrifice) | PAR-292 M28; the search parses |
| Vision Quest | "put it onto the battlefield with X additional +1/+1 counters on it. If X is 4 or greater, it gains haste until end of turn" with the bound "mana value X or less" | PAR-292 M28; the search parses |
| Turtle Tracks | "any number of target players" |  |
| Oath of Lieges | "target player who controls more lands" chosen at resolution |  |
| Restorative Technique | "gains 2 life, then searches" (subject carried across a clause) |  |
| Pir's Whim | friend / foe split |  |
| Clever Combo | "a host card or a card with augment" (keyword-quality union) |  |
| Hero's Uncle | "a legendary team-up creature" has no "card" noun |  |
| The Champion | negated type "that isn't a creature" plus its reveal-put-shuffle tail |  |
| Thawing Glaciers | delayed "return at the beginning of the next cleanup step" (cleanup grants no priority, RULE 514.3a) |  |
| Ruin in Their Wake | may-gated conditional put "if you control a land named wastes" |  |
| Verdant Mastery | puts under an opponent's control; kicker-cost condition |  |
| Signal the Clans | random choice among 3 cards with different names |  |
| Mitotic Manipulation | "same name as a permanent" |  |
| Hew the Entwood | sacrifice-count X plus a chosen subset, two destinations |  |
| Zimone's Experiment | two destinations by type among the revealed cards |  |
| Expand the Sphere | "fewer than 2 ... the difference" proliferate |  |
| Preferred Selection | sacrifice-and-pay, then pick |  |
| Depala, Pilot Exemplar | pay {x}, then reveal x |  |
| Sandstalker Moloch | intervening-if "an opponent cast a blue and/or black spell this turn" |  |
| Zurgo and Ojutai | extra "you may return 1 of those dragons" tail |  |
| Inferno Hellion | intervening-if "~ attacked or blocked this turn" |  |
| Etrata, the Silencer | "loses the game if they own 3 or more exiled cards with hit counters" |  |
| Fblthp, the Lost | "if your library has no cards in it, you win the game" |  |
| Rishadan Pawnshop | target kind "nontoken permanent you control" for an owner shuffle |  |
| Riftsweeper | target kind "face-up exiled card" |  |
| Oracle of Tragedy | minimum mana value on a graveyard target pick, plus its modal head |  |
| Trenzalore Clocktower | cost "remove 12 time counters from ~ and exile it" |  |
| Time Spiral | "untap up to 6 lands" |  |
| Jace, the Mind Sculptor | -12 (exile library, shuffle hand into library) |  |
| Symbiote Spider-Man | graveyard ability "Find New Host ... It gains this card's other abilities" | dig parses |
| Choco, Seeker of Paradise | "that many" = attacking-bird count, mixed pick |  |
| Duelist's Flame | granted trigger with a quoted dig |  |
| Glimpse of Tomorrow | "reveal that many" = the shuffled permanents |  |
| Ryan Sinclair | free cast only "if it's a spell with mana value less than or equal to Ryan's power" |  |
| Bismuth Mindrender | cast by paying life equal to the mana value |  |
| Black Widow, Super Spy | counter-or-cast window with mana of any type |  |
| Sunbird's Invocation | "from among cards revealed this way" plus X = that spell's mana value under a cast trigger |  |
| Svella, Ice Shaper | Icy Manalith token ability | dig parses |
| Aetherworks Marvel | energy clauses | dig parses |
| Kamahl's Druidic Vow | announced X under the spell plus "land and/or legendary permanent" union |  |
| Kayla's Reconstruction | "up to X" pick count |  |
| Birthing Ritual | X = 1 plus the sacrificed creature's mana value |  |
| Ayesha Tanaka, Armorer | "less than or equal to ~'s power" cap | cached text: re-check |
| Coralhelm Chronicler | "a card with a kicker ability" |  |
| Overgrown Pest | "a land or double-faced card" |  |
| Radagast the Brown | "doesn't share a creature type with a creature you control" |  |
| Getaway Barrel | "a random creature card" |  |
| Kotose, the Silent Spider | "for as long as you control Kotose, you may play one of the exiled cards" over the sweep's finds |  |
| Deadly Cover-Up | non-targeted pick from an opponent's graveyard behind the evidence condition |  |
| Haunting Echoes | "exile all cards from target player's graveyard other than basic land cards" | engine side exists |
| Gifts Given | library owner chooses; chosen to their graveyard, rest to the caster's hand |  |
| Emergent Ultimatum | split with an exile pile plus a free-cast window over the other pile |  |
| Jhoira, Ageless Innovator | "lose life equal to that permanent's mana value"; historic criteria misread (all permanent types) | hand-authored |
| M'Odo, the Gnarled Oracle | announced-X hit quality plus a command-zone activation restriction |  |
| Thought Dissector | "an artifact card or X cards, whichever comes first" plus conditional sacrifice |  |
| Tasha, the Witch Queen | counted dig of three creature cards plus its +1 / -2 |  |
| Thoughtpicker Witch | exile pick from a target opponent's top cards |  |
| Kayla's Music Box | look-at-top rest action |  |
| Agency Outfitter | two named slots over graveyard, hand and library |  |
| Fang-Druid Summoner | "with no abilities" card predicate |  |
| Mishra, Artificer Prodigy | "same name as that spell" referent of a cast trigger |  |
| Say Its Name | graveyard-exile cost with "other cards named ~" |  |
| Arachnus Spinner | "attached to target creature" needs a target the search's then_specs cannot bind; "tap an untapped spider" cost |  |
| Mwonvuli Beast Tracker | "Shuffle and put that card on top" as its own sentence after a reveal |  |
| Loyal Inventor | "into hand if you control an assassin, otherwise on top" after the shuffle |  |
| Rootwater Thief | "you may pay {2}. If you do, search that player's library" wrapper |  |
| Knowledge Exploitation | casts from the library, never exiled |  |
| Naughty // Nice | hand destination from another player's library |  |
| Earwig Squad | prowl (alternative cost and a prowl-paid flag) — PAR-299 | search sentence parses |
| Thada Adel, Acquisitor / Grinning Totem | "you may play that card" after a search-exile (`cast_window_exiled_pool` not wired to a search's finds) | pair |
| Scheming Symmetry / Varragoth, Bloodsky Sire | shuffle-then-put-on-top by another player | pair |
| Pattern of Rebirth / Verdant Succession | "that creature's controller" with a dying-trigger referent | pair |
| Hide in Plain Sight / Write into Being | cloak / manifest a looked-at card | pair |
| Azami's Familiar / Aladdin's Lamp | draw-replacement head (replacement family, PAR-294) | pair |
| Stream of Thought / Tamiyo, Seasoned Scholar | untargeted "shuffle up to N cards from your graveyard" pick | pair |
| Plunge into Darkness / Karn, Living Legacy | "pay any amount, then look at that many" | pair |
| Genesis Hydra / Knickknack Ouphe | announced X read under a cast / enters trigger | pair |
| Glacial Revelation | "snow permanent cards" (a supertype word with "permanent"; the criteria vocabulary refuses an AND of a type OR-list) | PAR-292 M29 |
| Michelangelo's Technique / Smelting Vat | "up to two ... cards with total mana value 6 or less" / "less than or equal to the sacrificed artifact's mana value": a total mana value cap on a dig pick (the choose-objects budget exists, the dig has no such bound) | PAR-292 M29; a pair |
| Rip, Spawn Hunter | "any number of creature and/or Vehicle cards with different powers" (a pairwise-distinct pick) | PAR-292 M29 |
| Eivor, Wolf-Kissed / Nashi, Searcher in the Dark / Rampant Frogantua | "you mill that many cards" (a mill count from the combat damage dealt) before a "from among them" pick (Eivor's Saga card and/or land card, Nashi's legendary and/or enchantment cards plus an "if you put no cards into your hand this way" counter, Frogantua's lands); the one-card-per-slot pick itself parses (Sludge Titan) | PAR-292 M29; Frogantua also prints a life-lost pump |
| Gilgamesh, Master-at-Arms | "when you put 1 or more Equipment onto the battlefield this way, attach one of them to target creature you control" after an any-number pick | PAR-292 M29 |
| Xenagos, the Reveler | "-6: exile the top 7 cards of your library. You may put any number of creature and/or land cards from among them onto the battlefield." (an exile dig, not a look) plus its mana ability | PAR-292 M29 |
| Doubling Chant / Clarion Ultimatum / Dire-Strain Rampage / From the Ashes / Wave of Vitriol | per-permanent search loops ("for each <permanent>, search ... same name" and one search per destroyed permanent, then "each player who searched their library this way shuffles"); Krenko's Buzzcrusher is the same loop | PAR-292 close; one loop primitive, unmeasured per card, no shape with 3 solo cards in the v1080 scan |
| Stomping Slabs / Sanity Grinding / Petals of Insight | reveal-then-bottom-all with no pick (the whole revealed pile goes to the bottom) | PAR-292 close; unmeasured per card (not re-checked at v1080) |
| Jodah, Archmage Eternal / Possibility Storm / Tibalt's Trickery / Unpredictable Cyclone / Guff Rewrites History | dig hits relative to a spell (a hit measured against the spell that triggered or was cast) | PAR-292 close; unmeasured per card (not re-checked at v1080) |
| Fludge / The Gunky Runner and the other gunk cards | "shuffle N <name> cards into their library" | PAR-292 close; unmeasured per card (not re-checked at v1080) |
| Field of Dreams / Wizened Snitches / Lantern of Insight / Yet Another Aether Vortex | static "players play with the top card of their libraries revealed" (the "your library" form is `activation_clauses`; the each-player form has no row); Lantern also prints "target player shuffles" | PAR-292 M29 re-measure: 2 solo (Field, Snitches) |
| Boggart Forager / Soldier of Fortune / Lantern of Insight | "target player shuffles [their library]" as an effect (the shuffle primitive and its target exist; M25 built only the controller's own form) | PAR-292 M29 re-measure: 2 solo (Forager, Soldier); with the static above Lantern is a third |

### Mana-ability rider residue (BUG-73 close, PARSER_VERSION 1061)

Cards that lost MODELED because a sentence after their `Add` clause is one `game/mana_abilities.py` does not execute (`parser/oracle/mana_riders.py` is the gate). Shared shapes with five or more cards are tracked as tickets in `BACKLOG.md`, not here; the rows below are the one-offs and the pairs/triples. Re-run the BUG-73 verdict diff before hand-authoring: a shared rider primitive may now reach them.

| Card | Gap | Notes |
| --- | --- | --- |
| Foraging Wickermaw | "`{1}`: Add one mana of any color. ~ becomes that color until end of turn." | the produced colour feeds a recolour |
| Black Tulip | "You can't activate this ability until you've begun your sixth turn of the game." | game-turn activation gate |
| Mana Cache | "Any player may activate this ability but only during their turn before the end step." | activator is not the controller |
| Rainbow Vale / Witch Engine | "an opponent gains control of ~ at the beginning of the next end step" / "Target opponent gains control of ~" | control change inside a mana ability (the second targets, so is not a mana ability) |
| Rubble Rouser / Shaun & Rebecca, Agents | "When you do, ~ deals N damage to each opponent." / "When you do, mill N cards." | reflexive trigger after a mana payment |
| Temur Elevator | "If you don't have the city's blessing, you lose N life." | blessing-gated life loss |
| Truss, Chief Engineer | "This effect can't reduce a number below N or a number word below N." | rider of a counter-reduction ability |
| Under-Construction Skyscraper / Vexing Puzzlebox | "Scry N." / "Roll a dN." | effect after the Add clause |
| Undiscovered Paradise | "During your next untap step, as you untap your permanents, return ~ to its owner's hand." | untap-step return |
| Mishra's Toy Workshop | "Spend this mana only on spells and abilities that put tokens onto the battlefield. Use toys to represent the tokens." | token-source restriction |
| Farrelite Priest / Initiates of the Ebon Hand | "If this ability has been activated N or more times this turn, sacrifice ~ at the beginning of the next end step." | pair: per-turn activation counter |
| Diamond Lion / Lion's Eye Diamond / Grinning Ignus | "Activate only as an instant." / "Activate only as a sorcery." | RULE 602.5d/602.5e on a mana ability; the cost has no sorcery-speed flag for mana abilities |
| Cavern of Souls / Delighted Halfling / Boseiju, Who Shelters All | "... and that spell can't be countered" / "that spell can't be countered" | triple: a spend-payoff that marks the cast spell uncounterable |
| Ether / Magus Lucea Kane / Sunken Palace | "When you next cast ... copy that spell. You may choose new targets for the copy." | triple: next-cast copy rider (RULE 707.10) |
| Sole Performer / Mox Lotus / Mons's Goblin Waiters | the Add clause prints a symbol the mana pool cannot hold (`{T}{T}`, `{∞}`, `{HR}`) | BUG-85 close |
| Axebane Guardian | "X mana in any combination ..., where X is the number of creatures you control with defender" | the builder's count subjects do not read the "with defender" filter |
| Squandered Resources | "Add one mana of any type the sacrificed land could produce" | cost-linked referent |
| Codie, Vociferous Codex | "When you next cast a spell this turn, exile cards from the top ... until an instant or sorcery with lesser mana value ..." | next-cast dig rider |
| Sorcerer Class / A-Sorcerer Class | "Spend this mana only to cast an instant or sorcery spell or to gain a class level." | MEC-174: paying a Class level-up cost is a special action the restriction predicates have no hook for (pair) |
| Adarkar Unicorn / Snowfall | "Spend this mana only to pay cumulative upkeep costs." | MEC-174: cumulative upkeep payments (RULE 702.24) take no restriction predicate (pair) |
| Freya Crescent / Ronin, Shadow Stalker | "... cast an Equipment spell or activate an equip ability(ies)" | MEC-174: the ability half names a keyword ability, but the activation predicate sees only the source (pair) |
| Karfell Harbinger / Niko Defies Destiny / Unblinking Observer / Qarsi Deceiver / Tin Street Gossip / Overgrown Zealot | "... foretell / pay a disturb cost / pay a morph cost / turn permanents face up" | MEC-174: special-action costs with no restriction hook beyond Creeping Peeper's `allow_face_up` |
| Echoing Cavern / Eclipsed Realms / ______ | "... spells of the chosen type[s]" | MEC-174: the chosen-type resolution (`chosen_type_spell`) reads one creature spell only |
| Jegantha, the Wellspring / The Rebellious Intelligence | "This mana can't be spent to pay generic mana costs." | MEC-174: a per-pip ban, needs `ManaPool` payment support, not a lot-level predicate (pair, plus Jegantha's companion line) |
| Heartwood Crafter // Soul Tether / Karolina Dean, Runaway / Vhal, Candlekeep Researcher | "This mana can't be spent to cast spells from your hand." | MEC-174: the negative twin of `spell_from_zone` (`not_zone` is a ban, this is a ban of one zone); triple, each also blocked elsewhere |
| Altar of the Lost / Corrupted Crossroads / Meeting of the Five / Titans' Nest / Watermarket / Secret Base / Jasmine Boreal of the Seven / Second City / Volshe Tideturner / Thieving Varmint / The Mystical Archive / The Charitable Drafter / Ice Cauldron / Chandra's Embercat / Brotherhood Headquarters / Cultivator Drone / Eldrazi Temple / Quinjet Technician / Mishra's Toy Workshop | one-off spell or ability characteristics in the "Spend this mana only ..." clause (devoid, exactly three colors, watermark, no abilities, second spell this turn, kicked, not from the starting deck, not owned, last card exiled with this artifact, power-up abilities, token-making abilities, compound subtype+type) | MEC-174: no shared shape; each needs its own spell/ability predicate |

### Mana-ability rider residue (MEC-175 close, PARSER_VERSION 1068)

The shared shapes are built (`ManaAbility.instead` / `gain_life` / `draw_cards` / `delayed_draw_cards` / `sacrifice_when_no_counters`, the wider "Activate only if" reader `mana_riders.mana_condition_dict`, and the spend / next-cast payoffs life, scry, draw, haste, X draw). What is left misses one unshared piece.

| Card | Gap | Notes |
| --- | --- | --- |
| Incubation Druid | "If this creature has a +1/+1 counter on it, add three mana of that type instead." | the replacement names the first clause's chosen type ("of that type"), not a fixed production |
| Altar of the Pantheon | "If you control a God, a Demigod, or a legendary enchantment, you gain 1 life." | `static_condition` reads "a legendary enchantment" as the creature-only `control_legendary_subtype`; a legendary-permanent-of-type count is the missing condition |
| Brood Astronomer | "If you control a Planet with twelve or more charge counters on it, add three mana of any one color instead." | a counter threshold on a permanent subtype, an Alchemy spellbook card besides |
| Undermountain Adventurer | "If you've completed a dungeon, add 6 {G} instead." | the replacement prints a count before the symbol ("6 {G}"), outside the clause grammar |
| A-Town | "If you're in a city that starts with an A, instead add one mana of any color." | Alchemy only |
| Urza's Fun House | "Activate only once and only if you control an Urza's Mine, ..." | `{∞}` mana, plus an unreadable internet-visit ability |
| Manaforge Cinder / Lavinia, Foil to Conspiracy | "Activate no more than three times each turn." / "Activate only during an opponent's turn." | activation caps the cost grammar has no flag for (pair) |
| The Secret Lair / Under-Construction Skyscraper | "Scry 1." after the Add clause | an immediate scry rider; the Lair also says a secret word |
| Grove of the Burnwillows / Cryptolith Fragment | "Each opponent gains 1 life." / "Each player loses 1 life." | a life effect aimed at other players (pair) |
| Pyromancer's Goggles / Forger's Foundry / Andrios, Roaming Explorer / Boseiju, Who Shelters All / Second City | spend payoffs that copy, exile, reset base P/T, make an uncounterable spell or create a token | each needs its own post-cast effect |

### Reflexive-referent residue (MEC-171, PARSER_VERSION 1065)

Cards whose "When you do" payoff reads what the earlier instruction moved, and that still miss one unshared piece. The recorded referent itself (`cost_referents`, snapshotted onto the reflexive trigger) is built; Argentum Masticore, Nihiloor and Grishnákh wait for MEC-172's target bound, not for a new record.

| Card | Gap | Notes |
| --- | --- | --- |
| Surtland Flinger | `if the sacrificed creature was a giant, ~ deals twice that much damage instead.` | "twice that much ... instead" replacement over a bound amount; no second card in the cache has the shape |
| Bolg of the North | `~ deals damage equal to that creature's power to another target creature. if excess damage was dealt this way, amass goblins x, where x is that excess damage.` | excess-damage amount of the reflexive hit feeding an amass |
| Stet, Draconic Proofreader | `~ deals 4 damage to any target whose name begins with the same letter as the exiled card.` | target filter on the first letter of the recorded card's name |
| Bullseye, Death Dealer | `you may sacrifice an artifact or discard a nonland card. when you do, ...` | an either-or antecedent (one cost of two kinds) in a `pay_cost_then`; Anthropede ("discard a card or pay {2}") and Nimble Hobbit ("sacrifice a Food or pay {2}{W}") share it, so a three-card `pay_cost_then` alternative cost is the ticket to write if it is wanted |

### Target-bound residue (MEC-172, PARSER_VERSION 1066)

The bound itself (`max_mana_value {"count_selector"}` / `stat_count_bound` over a recorded referent) is built; these cards miss a different piece.

| Card | Gap | Notes |
| --- | --- | --- |
| Mandate of Abaddon, Fell the Mighty | `destroy all creatures with power less than that creature's power.` / `...greater than target creature's power.` | a *group* filter compared with an announced target's stat (a `group` selector whose `stat_count_bound` reads that target); `GROUP_REFERENCES` only knows `trigger_subject`, and Mandate's "choose target creature you control" pre-sentence is its own shape. Two cards |
| Nihiloor | `for each opponent, tap up to one untapped creature you control. ... creature's power` | per-opponent scoping of a tap `record_referent` plus "for as long as you control ~" steal and a second attack trigger; no shared piece beyond the bound |
| Saruman of Many Colors | `when one or more cards are milled this way, exile target ... with mana value less than or equal to that spell's mana value ... copy the exiled card` | "milled this way" reflexive trigger, the cast spell as referent, and copy-and-cast of the exiled card |
| Annex Sentry | `artifact_or_creature_you_dont_control` target frame ignores `max_mana_value` | a one-line `TargetFrame(apply_max_mana_value=True)` check, found by the MEC-172 frame sweep; unrelated to referents |

### Player-scoped residue (PAR-291 M2 sizing)

Sized with `parser_probe blocked` at v1071: "each player returns / exiles / puts ... from their graveyard / hand" has 10 solo cards and no shared piece larger than two.

| Card | Gap | Notes |
| --- | --- | --- |
| Living End, Scrap Mastery | `each player exiles all <type> cards from their graveyard, then sacrifices all <type>s they control, then puts all cards they exiled this way onto the battlefield.` | per-player mass exile into a per-player pool, a mass sacrifice, then a return of that pool under owners' control; needs an "exiled this way" per-player pool (the mass-exile row has none) |
| Memory Jar, Magus of the Jar | `each player exiles all cards from their hand face down and draws 7 cards. At the beginning of the next end step, each player discards their hand and returns to their hand each card they exiled this way.` | per-player face-down hand exile pool plus a delayed return |
| Balthor the Defiled | `each player returns all black and all red creature cards from their graveyard to the battlefield.` | a colour union on the mass return (`ReturnFromGraveyardEffect` mass path ignores `colors`); the only colour-qualified mass return open |
| Bloodbond March | `each player returns all cards with the same name as that spell from their graveyard to the battlefield.` | spell-relative name filter on the mass return |
| Patriarch's Bidding | `each player returns all creature cards of a type chosen this way from their graveyard to the battlefield.` | per-player creature-type choices (union) feeding a mass return |
| Bringer of the Last Gift | `each player returns all creature cards from their graveyard that weren't put there this way to the battlefield.` | "put there this way" exclusion set after a mass sacrifice |
| All Hallow's Eve | `put it into your graveyard and each player returns all creature cards from their graveyard to the battlefield.` | the mass return itself is claimed; the open part is the self-move of the exiled source from exile |
| Sadistic Augermage | `when ~ dies, each player puts a card from their hand on top of their library.` | per-player hand-to-library pick (PAR-292's hand-to-library action, scoped to each player) |
| Overburden, Confounding Conundrum | `that player returns a land they control to its owner's hand.` | the bounce itself is claimed; the head names the player of a land / creature entering (`ENTERS_BATTLEFIELD` is not in the edict's "that player" event list) |
| Strategic Betrayal | `target opponent exiles a creature they control and their graveyard.` | an exile edict plus the same player's whole graveyard in one sentence |
| Discovery // Dispersal | `each opponent returns a nonland permanent they control with the greatest mana value among permanents they control to its owner's hand, then discards a card.` | the "greatest mana value" bounce over a nonland pool plus a chained discard |
| Umbilicus | `that player may pay 2 life. If they don't, they return a permanent they control to its owner's hand.` | the may-pay-else form of the punisher (Blood Clock's sibling) |

### Player-scoped residue (PAR-291 M3 sizing)

Sized with `parser_probe blocked` at v1072 after the M3 rows landed: player-scoped token creation, "exiles the top card of their library" with riders, "chooses ... then sacrifices the rest" and "discards all <class> cards" have no shape of three or more solo cards left; every row below is a one-off or a pair.

| Card | Gap | Notes |
| --- | --- | --- |
| Balefang the Unslayable, Hansk Slayer Zealot, Davvol's Birthdaymobile, The Sentry Golden Guardian | `target opponent creates a [tapped] <named token>` | the creator scope exists (`create_token` `creators: target`); the tokens (Baneslayer Angel, Walker, Carnival of Souls, The Void) are not curated in `data/tokens.json`, so `NAMED_TOKEN_WORDS` cannot claim them (a blank synthesized token would drop its abilities); four distinct tokens, authored or added one by one |
| Eiganjo Uprising | `each opponent creates x minus 1 2/2 white samurai creature tokens with vigilance.` | "x minus 1" token count under a player scope |
| Death by Dragons | `each player other than target player creates a 5/5 red dragon creature token with flying.` | "each player other than target player" scope |
| Inscription of Insight, Phantasmal Sphere, Dovescape, Pure Reflection | `<player> creates an x/x <token>, where x is ...` | the x/x token with a where-x power is open even for "you create" (no creator scope involved); a PAR ticket on its own, 4 cards plus the "you" form |
| Pursued Whale, Relic Robber, Kibo Uktabi Prince, Rite of the Raging Storm | `<player> creates a token with "<quoted ability>"` | the quoted-ability tail of a player-scoped token |
| Pyxis of Pandemonium, Rocco Street Chef, Timesifter, Triple Triad, Crabomination, Xander's Pact | `each player / opponent exiles the top card ... ` plus a per-player "exiled this way" play / cast rider | the exile row is claimed; each rider is different (face-down turn up, play "the card they exiled this way", greatest mana value takes a turn, cast with life payment) |
| Mind Extraction, Crosis the Purger, Persecute Artist, Tsabo's Decree, Void, Rare-B-Gone | `reveals their hand and discards all <class> cards` where the class is a referent (a sacrificed creature's colors, a chosen color / artist / type / number) or a rarity | the row takes printed classes only; each referent is a different antecedent |
| Stick Together | `each player chooses a party from among creatures they control, then sacrifices the rest.` | party slots (one each of Cleric, Rogue, Warrior, Wizard, a creature fills one slot, RULE 700.8) are not the per-type keepers of `keep_types` |
| Destined Confrontation, Balancing Act, Mythos of Snapdax | `each player chooses any number of creatures with total power 4 or less ...` / `a number of permanents ... equal to the fewest ...` / `... if {B}{R} was spent, you choose` | a total-power cap, a fewest-count measure, and a cost-conditional chooser |

### Player-scoped residue (PAR-291 M4 sizing)

Sized with `parser_probe blocked` at v1073, then rebuilt at v1074 (tempting offer, shared damage draw). No player-scoped shape of three or more solo cards is left: every row below is a one- or two-card shape, or its bodies are distinct one-offs.

| Card | Gap | Notes |
| --- | --- | --- |
| Master of Ceremonies, Seize the Spotlight | `each opponent chooses money, friends, or secrets. For each player who chose money, you and that player each create a Treasure token ...` / `each opponent chooses fame or fortune. For each player who chose fame, gain control ...` | a per-opponent named choice, then per-choice payoffs counted over the choosers (2 cards, distinct payoffs) |
| Maître Tree | `each opponent may also create a token from the menu. For each opponent who does, you create a token of the same type.` | the offer shape is claimed (`tempting_offer`); open is the menu (modal token choice) |
| Tempt with Discovery, Tempt with Mayhem | `For each opponent who searches a library this way ...` / `You copy that spell once plus an additional time for each opponent who copied the spell this way.` | Discovery is hand-authored; Mayhem counts copies of a spell (amount "plus one per acceptor") |
| Khorvath's Fury, Pir's Whim, Regna's Sanction, Virtus's Maneuver, Zndrsplt's Judgment | `for each player, choose friend or foe. Each friend <X>. Each foe <Y>.` | the friend / foe head is one shape (5 cards) but only Pir's Whim has both bodies claimed today ("each player puts a counter on each creature they control", "each player returns a creature card from their graveyard to their hand", "each player creates a token that's a copy of a creature they control", "taps the rest", "discards all then draws that many plus 1" are all open as plain `each player` rows); promote the bodies first |
| Cait Cage Brawler, The River Warlock | `you and defending player each draw a card, then discard a card. <conditional on the discarded mana values>` | the shared draw / discard is claimable, the greatest-mana-value-among-both-discards rider is not (2 cards) |
| Yume, Chronicler of Valor | `when you cast that spell, if another player spent mana to cast it, you and that player each draw a card.` | "that player" is the assisting player (no referent row) |
| Battle at the Helvault, Vault 13: Dweller's Journey | `for each player, exile up to 1 target ... that player controls until this saga leaves the battlefield.` | per-player target rounds are claimed; the saga-lifetime exile ("until this saga leaves") is not (2 cards) |
| Demonic Junker, Unexplained Absence, Krenko's Buzzcrusher, Guff Rewrites History, Vaevictis Asmadi, Ghouls' Night Out, Winnowing | `for each player, destroy / exile up to 1 ... that player controls.` plus a per-player rider | each rider is different ("if a creature you controlled was destroyed this way", "its controller cloaks the top card", "for each land destroyed this way its controller may search", ...) |
| Incite Rebellion | `for each player, ~ deals damage to that player and each creature that player controls equal to the number of creatures they control.` | per-player damage amount measured per player |
| Lim-Dul's Hex | `for each player, ~ deals 1 damage to that player unless they pay {B} or {3}.` | an OR of two costs in the mass "unless" row |
| Elminster's Simulacrum | `For each opponent, you create a token that's a copy of up to one target creature that player controls.` | per-opponent copy target round |
| Overburden, Confounding Conundrum, Discovery // Dispersal, Umbilicus | the M2 sizing rows (entering-permanent "that player", greatest-mana-value bounce, may-pay-else) | still one card each |
| Nature's Wrath | `whenever a player puts an island or blue permanent onto the battlefield, that player sacrifices an island or blue permanent of their choice.` | the only open cross-dimension "<land type> or <color> permanent" pool at v1074 (orchestrator sizing) |

### Player-scoped residue (PAR-291 M5 sizing)

The "each opponent exiles cards from the top of their library until ..." family was built at v1075 (Fevered Suspicion, Dream Harvest, Tasha's Hideous Laughter, Krang & Shredder). What is left of it is one-off riders. Friend / foe was re-sized: the head (a per-player choice by the controller, then two filtered per-player loops) would unlock Pir's Whim alone; every other friend / foe body, and even Pir's foe body ("each player sacrifices an artifact or enchantment of their choice"), is an open plain `each player` row, so the head costs engine work for one card until the nine bodies exist.

| Card | Gap | Notes |
| --- | --- | --- |
| Bismuth Mindrender | `that player exiles cards from the top of their library until they exile a nonland card. You may cast that card by paying life equal to the spell's mana value rather than paying its mana cost.` | the dig is the claimed `event_player` row; the cast rider needs a per-card life-for-mana alternative cost inside the resolution play (the existing `pay_life_equal_mv` is a standing static grant) |
| Black Widow, Super Spy | `... until they exile a nonland card. You may put a +1/+1 counter on Black Widow. If you don't, you may cast the exiled nonland card until end of turn and mana of any type can be spent to cast that spell.` | an optional counter, an "if you don't" branch and a mana-type wildcard cast window (one card) |
| Wand of Wonder | `Roll a d20. Each opponent exiles cards from the top of their library until they exile an instant or sorcery card, then shuffles the rest into their library. You may cast up to X instant and/or sorcery spells ...` | die-result table sets X (1 / 2 / 3), a "shuffles the rest" tail and the "instant and/or sorcery" cast cap; the dig itself is `dig_each_opponent` plus the predicate "an instant or sorcery" |
| Umbris, Fear Manifest | `~ gets +1/+1 for each card your opponents own in exile.` | the trigger body ("target opponent exiles ... until they exile a land card") has no row for a bare land hit; the static counts opponent-owned exile cards |
| Guff Rewrites History, Seek Bolas's Counsel | `Each player who controlled one of those permanents exiles cards ... until they exile a nonland card, then puts the rest on the bottom ... Each player may cast the nonland card they exiled.` / `For each opponent, exile cards from the top of their library until you exile a nonland card. You may cast those cards ...` | per-player casts of their own digs after a shuffle-away; a random mode among six with an emblem, a planeswalk and a mass destroy |
| Khorvath's Fury, Pir's Whim, Regna's Sanction, Virtus's Maneuver, Zndrsplt's Judgment | `for each player, choose friend or foe. Each friend <X>. Each foe <Y>.` | the nine bodies: wheel plus one / damage equal to hand size (Khorvath); land search tapped / sacrifice an artifact or enchantment (Pir); counters on each creature they control / choose one untapped creature, tap the rest (Regna); return a creature card from graveyard / sacrifice a creature (Virtus); copy a creature they control / return a creature they control to hand (Zndrsplt): all open as plain `each player` rows; promote the bodies as a PAR ticket before the head |

### Player-scoped residue (PAR-291 close)

The residue PAR-291 carried that the M2..M5 sizing sections do not list. Raging River is in PAR-298, Worldfire in
PAR-303, Dark Deal above, and the "if you would lose the game, instead" life sets in PAR-294.

| Card | Gap | Notes |
| --- | --- | --- |
| Stand or Fall, Butcher Orgg | multi-player scopes (piles per defending player, damage divided among several players' creatures) | each scope is its own choice structure |
| Cait Cage Brawler, The River Warlock | `you and defending player each draw a card, then discard a card` plus a greatest-mana-value rider | also listed in the M4 section; "defending player" has no shared-draw row |
| Master of Cruelties | `that player's life total becomes 1` on an attack trigger | needs a defending-player selector for the life-set row |
| Invincible Hymn, Touch of the Eternal | `... life total becomes that number` after a count sentence | the amount is the previous sentence's count |
| Long Rest, Elderscale Wurm | conditional life sets ("if ... ", "as long as ... life total can't be reduced below 7") | condition / floor, not the set itself |
| Sway of the Stars, Once More with Feeling, Oketra's Last Mercy | a life set after unclaimed sentences (shuffles, restarts, land skips) | the set claims; the other sentences do not |
| Awaken the Erstwhile | `each player discards all the cards in their hand, then creates that many 2/2 black Zombie tokens` | per-player "that many" from their own discard |
| Flux | `each player discards any number of cards, then draws that many cards` | "any number" chooser discard per player |
| Collision of Realms | `each player shuffles a creature they control into their library. each player who shuffled ... reveals cards until ...` | per-player dig keyed to the shuffled card |
### Unsupported Rooms (reference only; not actionable queue entries)

These explain the remaining Room coverage denominator and must not be treated as implementation work: `Crude Abattoir // Unsavory Kitchen`, `Solitary Study // Endless Corridor`. Both return `NEVER_SUPPORTED` because their Alchemy halves are a permanent non-goal.
