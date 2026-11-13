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

### Flip cards (6 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Akki Lavarunner // Tok-Tok, Volcano Born | `if a red source would deal damage to a player, it deals that much damage plus 1 to that player instead.` | Current unclaimed clauses; singleton/cluster check pending. |
| Curse of the Fire Penguin // Curse of the Fire Penguin Creature | `~ consumes and confuses enchanted creature.`; `when ~ dies, return curse of the fire penguin to the battlefield.` | Current unclaimed clauses; singleton/cluster check pending. |
| Homura, Human Ascendant // Homura's Essence | `when ~ dies, return it to the battlefield flipped.`; `creatures you control get +2/+2 and have flying and "{r}: ~ gets +1/+0 until end of turn."` | Current unclaimed clauses; singleton/cluster check pending. |
| Kitsune Mystic // Autumn-Tail, Kitsune Sage | `at the beginning of the end step, if ~ is enchanted by 2 or more auras, flip it.`; `{1}: attach target aura attached to a creature to another creature.` | Current unclaimed clauses; singleton/cluster check pending. |
| Sasaya, Orochi Ascendant // Sasaya's Essence | `reveal your hand: if you have 7 or more land cards in your hand, flip ~.`; `whenever a land you control is tapped for mana, add an additional 1 mana of any type that land produced for each other land you control with the same name as it.` | Current unclaimed clauses; singleton/cluster check pending. |
| Student of Elements // Tobita, Master of Winds | `when ~ has flying, flip it.` | Current unclaimed clauses; singleton/cluster check pending. |

### Flash-permission residue (PAR-226 close, PARSER_VERSION 825)

| Card | Gap | Notes |
| --- | --- | --- |
| Savage Summoning | next creature spell "enters with an additional +1/+1 counter" | Flash and uncounterable halves exist; needs a spell-bound one-shot ETB-counter stamp (a floating `extra_etb_counter` would hit every creature cast that turn). |
| Progenitor's Icon | next-spell flash over the source's chosen creature type | Needs a chosen-type next-spell grant. |
| Radagast of Rhosgobel | "first creature spell each turn costs {2} less" | No self-cost row for a first-spell-each-turn reduction. |
| Cherished Hatchling | dies trigger: Dinosaur spells have flash this turn, plus cast trigger granting a fight ability | Bundle of two temporary grants. |
| Rootwater Shaman | "Aura spells with enchant creature" flash | No enchant-restriction filter on `flash_permission`. |
| Keeper of the Secret Lair | "Secret Lair" spells | No card predicate for the Secret Lair set. |
| Azula, Cunning Usurper | exile-linked cast permission with bundled flash | — |
| Fated Clash; Silver Scrutiny; Quantum Reduction; Tegwyll's Scouring | "you may cast this spell as though it had flash if <state>" | Conditions not yet parsed (attacking+blocking creature, X ≤ 3, teamwork, tap-three-fliers cost); promote to a ticket if two share a condition. |

### Quantity-threshold head residue (PAR-231 close, PARSER_VERSION 833)

| Card | Gap | Notes |
| --- | --- | --- |
| Anje, Maid of Dishonor | `whenever ~ and/or 1 or more other vampires you control enter` (once each turn) | Self-or-group entry batch with a subtype filter. |
| Bloodletter | `when the names of 3 or more nonland permanents begin with the same letter` | State trigger over name initials. |
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
| Kaya, Spirits' Justice | `whenever 1 or more creatures you control and/or creature cards in your graveyard are put into exile` | Mixed battlefield/graveyard exile batch plus a copy body. |
| The War Doctor | `whenever 1 or more other permanents phase out and whenever 1 or more other cards are put into exile from anywhere` | Double head; phase-out batch missing, exile half exists (v833). |
| Hero of Bretagard; Ranar the Ever-Watchful | `whenever 1 or more cards are put into exile from your hand or a spell or ability you control exiles 1 or more permanents from the battlefield` | Shared pair, both blocked by other clauses as well; promote together once those land. |
| The Heron Moon | body: release counter, at 13 or more sacrifice it and cast a copy of Emrakul, the Promised End | Head parses (v833 exile batch). |
| Ketramose, the New Dawn | `~ can't attack or block unless there are 7 or more cards in exile` | Head parses (v833). |
| Breeches, Brazen Plunderer | body: `exile the top card of each of those opponents' libraries ...` | Head parses (v833 damage batch). |
| Screeching Scorchbeast | body: `you may create that many ... do this only once each turn` | Head and `nonland_count` exist (v832). |
| Sand Scout | body: the `red, green, and white` token | Head parses (v832). |
| Flummoxed Cyclops | body: `can't block this combat` | Head parses (v831). |

### Attachment-head residue (PAR-234 close, PARSER_VERSION 834)

| Card | Gap | Notes |
| --- | --- | --- |
| Grievous Wound | static: `enchanted player can't gain life` | `enchanted player is dealt damage` head parses since v834. |
| Archnemesis | `whenever you attack enchanted player` and `whenever a player attacks you, you may attach ~ to that player` | Actor-you form is excluded in `player_event_head`. |
| Eriette, the Beguiler | Aura becomes attached to a nonland permanent an opponent controls with mana value at most that Aura's | Attach-host filter with a comparison to the Aura. |

### Subject-filter residue (PAR-233 close, PARSER_VERSION 836)

| Card | Gap | Notes |
| --- | --- | --- |
| Nyx Herald | target `enchanted creature or enchantment creature you control` may name the Herald itself | `permanent_you_control` excludes the source and can't tell "target" from "another target"; fail-closed guard `_source_excluded_union` (v836). |
| King of the Oathbreakers | body: `it phases out` | Head parses since v836. |
| Visitor from Planet Q | `all creature cards you own with flash are instants in addition to their other types` | Head and `min_card_types` exist (v836). |
| Shadow the Hedgehog | `each spell you cast has split second if mana from an artifact was spent to cast it` | Head parses since v836. |
| Last Laugh | `when no creatures are on the battlefield, sacrifice ~` | State trigger (RULE 603.8). |
| Astral Drift | `whenever you cycle this card or cycle another card while ~ is on the battlefield` | Self-or-another cycle head with a zone condition. |
| Marvel Boy, Noh-Varr | `whenever another creature you control enters and whenever you activate a power-up ability` | Power-up activation event. |

### Cast- and target-head residue (PAR-236 close, PARSER_VERSION 837)

| Card | Gap | Notes |
| --- | --- | --- |
| Danitha, Sword of Hope | `whenever you cast an equipment spell or a spell that targets a creature you control` (once each turn) | Disjunction over the spell itself; one trigger per spell. |
| Leyline of Combustion | `whenever you and/or at least 1 permanent you control becomes the target of a spell or ability an opponent controls` | Triggers once per spell however many of your things it targets (ruling); the v837 coordinated head triggers per target. |
| Giant Shark | `whenever ~ blocks or becomes blocked by a creature that has been dealt damage this turn` | Phrase tail missing; `damaged_this_turn` filter key already exists in `combat.matches_object_filter`. |
| Loki, God of Mischief | `whenever a player or permanent becomes the target of an ability you control` (once each turn) | Ability-only targeting source filter. |
| Mirror-Shield Hoplite | `whenever a creature you control becomes the target of a backup ability, copy that ability` | Backup-ability source filter plus ability copy. |

### Activation-cost residue (PAR-232 close, PARSER_VERSION 838)

| Card | Gap | Notes |
| --- | --- | --- |
| Benthic Explorers | cost: `{t}, untap a tapped land an opponent controls`; effect: `add 1 mana of any type that land could produce` | Untap-others grammar reads only "you control"; the mana ability needs the picked land's producible types (PAR-247 close, v839). |
| Illuminated Folio | cost: `reveal 2 cards from your hand that share a color` |  |
| Weight of Conscience | cost: `tap 2 untapped creatures you control that share a creature type` |  |
| Mossbridge Troll | cost: `tap any number of untapped creatures you control other than ~ with total power 10 or greater` |  |
| The Archimandrite | cost: `tap 3 untapped advisors, artificers, and/or monks you control` | Subtype-union tap cost. |
| Magosi, the Waterveil | cost: remove an eon counter and return ~ to its owner's hand |  |
| Sphinx of the Chimes | cost: discard two nonland cards with the same name |  |
| Jandor's Ring | cost: discard the last card you drew this turn |  |
| Knollspine Invocation | cost: `discard a card with mana value x` |  |
| Ormos, Archive Keeper | cost: discard cards with different names |  |
| Krovikan Sorcerer | cost: discard a nonblack card (and the black-card branch) |  |
| Fabrication Foundry | cost: exile one or more other artifacts you control with total mana value X |  |
| Nivmagus Elemental | cost: exile an instant or sorcery spell you control | Exiling a spell from the stack as a cost. |
| Tomb of Urami | cost: `sacrifice all lands you control` |  |
| Thelon of Havenwood | `{b}{g}, exile a fungus card from a graveyard: put a spore counter on each fungus on the battlefield` | Any-graveyard exile is pickable since BUG-53; the Fungus spore-counter static is the remaining gap. |
| Painbringer | `{t}, exile any number of cards from your graveyard: target creature gets -x/-x`, X = cards exiled | Needs an "any number" graveyard-exile count feeding X (BUG-53 close, v840). |

### Escape rider residue (PAR-239 close, PARSER_VERSION 844)

Cards next to the plain "escapes with N counters" shape, each probed SOLO on 1. Re-run `parser_probe.py blocked` on the clause before authoring.

| Card | Gap | Notes |
| --- | --- | --- |
| Charred Graverobber | `when ~ enters, return target outlaw card from your graveyard to your hand.` | Its `escapes with` line is claimed; the `outlaw` card target filter is the only blocker. |
| Pharika's Spawn | `~ escapes with 2 +1/+1 counters on it. when it enters this way, each opponent sacrifices a non-gorgon creature of their choice.` | Needs an Escape-only reflexive trigger next to the counters. |
| Polukranos, Unchained | `~ enters with 6 +1/+1 counters on it. it escapes with 12 +1/+1 counters on it instead.` | The Escape amount replaces the printed enters-with amount. |
| Skyway Robber | `~ escapes with "whenever ~ deals combat damage to a player, you may cast an artifact, instant, or sorcery spell from among cards exiled with ~ without paying its mana cost."` | Escape grants a quoted ability over the cards exiled with it. |
| Tizerus Charger | `~ escapes with your choice of a +1/+1 counter or a flying counter on it.` | Counter-kind choice as it enters (RULE 614.1c). |

### Copy-exception residue (PAR-253 close, PARSER_VERSION 850)

The `except it has` tail parses for these; each is blocked by another clause.

| Card | Gap | Notes |
| --- | --- | --- |
| Court of Vantress | `if you're not the monarch, you may have ~ become a copy of it, except it has this ability.` | After an optional `you may create a token that's a copy of it`, the reading loses the target, so `it` reads as the created token. |
| Curie, Emergent Intelligence | `whenever ~ deals combat damage to a player, draw cards equal to its base power.` | Needs a base-power amount and a copy of the object exiled as a cost. |
| Face Yourself | `... except it has haste and "at the beginning of the end step, if you don't control a planeswalker, sacrifice ~."` | The quoted condition is unclaimed; `copy_permanent` has no `add_ability_lines` consumer. |
| Firion, Wild Rose Warrior | `... except it has "~'s equip abilities cost {2} less to activate." sacrifice that token at the beginning of the next upkeep.` | Equip-cost reduction in a quoted ability; token copy. |
| Kaya, Spirits' Justice | `whenever 1 or more creatures you control and/or creature cards in your graveyard are put into exile, you may choose a creature card from among them.` | Batch-exile choice, plus an unclaimed -2. |
| Mirage Phalanx | `as long as ~ is paired with another creature, each of those creatures has "at the beginning of combat on your turn, create a token that's a copy of ~, except it has haste and loses soulbond. exile it at end of combat."` | Soulbond-granted trigger; the quoted copy needs `loses soulbond` and a two-sentence body. |
| The Cosplayzer | `... except it has "the first time each turn an ability of ~ is activated or triggered, copy it. ..." and the first letter of its name is z.` | Ability-copy trigger and a name-letter exception. |
| Vesuvan Drifter | `if you reveal a creature card this way, ~ becomes a copy of that card until end of turn, except it has flying.` | Needs a referent for the revealed top card. |
| Zedruu the Greathearted | `at the beginning of your upkeep, you gain x life and draw x cards, where x is the number of permanents you own that your opponents control.` | PAR-277 residue (v876): the donate ability parses; needs an "owned by you, controlled by an opponent" count phrase. |

### Star Trek (TRK + TRC) one-offs (50 rows, 2026-11-10, PARSER_VERSION 870)

Open Star Trek cards that fit none of the MEC-139..143 / ENG-55 / PAR-258..276 families in [BACKLOG.md](BACKLOG.md). Seven are Sagas, about a dozen are Spacecraft with a unique ability; several also need a primitive from those tickets first (assimilate, face a dilemma, differently named lands). Re-check each with `parser_probe.py blocked` after those tickets land: a new primitive often turns two of these into a cluster.

| Card | Gap | Notes |
| --- | --- | --- |
| Commander Spock | `whenever ~ enters or attacks, reveal the top card of your library. you may cast that card without paying its mana cost if that spell's mana value is equal to or less than the number of differently named lands you control. if it's a land card, you may put it onto the battlefield tapped. if that card is still on top of your library, draw a card.` | Blocked: composable except the closing 'if that card is still on top of your library, draw a card' -- no predicate asks whether the revealed card is still on top (cast_window_exiled_pool pool_zone=library checks it internally; reveal_top/put_revealed_card/amount_compare exist). Needs a 'revealed card still on top' condition in effect_conditions.py. |
| Ensign Pavel Chekov | `when ~ enters, each opponent exiles the top x cards of their library, where x is the number of differently named lands you control. for each opponent, choose a land card that player owns exiled this way. you may play the chosen cards for as long as they remain exiled.` | Not authored: 'for each opponent, choose a land card that player owns exiled this way' then 'play the chosen cards' has no per-opponent chooser over an exiled pool (exile_top_of_library + play_cards_exiled_with_source exist). Needs the chooser primitive. |
| Lieutenant Nyota Uhura | `{4}, {t}: target opponent exiles the top x cards of their library, where x is the number of differently named lands you control. you may cast an instant or sorcery spell from among them without paying its mana cost. then that player puts the rest on the bottom of their library in a random order.` | Blocked: 'puts the rest on the bottom of their library in a random order' has no exile-pool-to-library-bottom-random primitive (only graveyard_to_library_bottom_random); cast_window_exiled_pool covers the free instant/sorcery cast. |
| Chief Montgomery Scott | `{6}, {t}: you may put a creature or spacecraft card from your hand onto the battlefield. it enters with x additional +1/+1 counters on it if it's a creature and x additional charge counters on it if it's a spacecraft, where x is the number of differently named lands you control.` | Blocked: put_from_hand_onto_battlefield has no 'enters with additional counters' parameter; placed_effects would add the counters after entry, which is not 'enters with' (replacement-time) behaviour. |
| Species 8472 | `~ can't be the target of abilities from artifact sources your opponents control.` | Blocked: targeting._targetable_by has no restriction 'abilities from artifact sources your opponents control' (only protection, hexproof, shroud, hexproof from instants/own colours); needs a quality-scoped untargetable check in targeting.py. |
| 70,000 Light-Years from Home | `exile target creature or spacecraft. its controller may search their library for a basic land card, reveal it, put it into their hand, then shuffle.` | Blocked: exile_controller_searches_basic_land puts the land onto the battlefield tapped, not into hand. |
| All Good Things... | `i, ii, iii — draw 2 cards, then exile a card from your hand. \|\| iv — if all cards exiled with this saga share a card type, you gain 10 life.` | Blocked: (1) `ExileHandCardEffect` (effects/damage_draw.py; registry.py `exile_hand_card`) has no `track_exiled_with`, so the card exiled from hand never lands on the Saga's `exiled_with_ids`; (2) no condition 'all cards exiled with this source share a card type' in effect_conditions.py/static_conditions.py (only `shares_type_with_linked_exile`, one played card vs one linked card, and `milled_cards_share_all_types`). |
| Ambulatory Reactor | `artifact creatures you control have "{t}: add {c}. spend this mana only to cast an artifact spell or activate an ability of an artifact source."` | Blocked: grant_mana_ability's spend restriction type_spell matches creature subtypes only (continuous._has_subtype), so 'cast an artifact spell or activate an ability of an artifact source' is unusable (the artifact spell cannot be cast); needs an artifact card-type restriction kind in mana_abilities.py. |
| Borg Incursion | `create 2 1/1 colorless borg artifact creature tokens, then artifact creatures you control gain protection from the color of your choice until end of turn.` | Blocked: no group-wide single-colour protection choice primitive (grant_protection group supports only 'shares'). |
| Brazen Bluff | `choose target noncreature spell an opponent controls. that player may exile it. if they don't, you may cast a noncreature spell from your hand without paying its mana cost.` | Blocked: 'that spell's controller may exile it; if they don't, you may cast a noncreature spell from your hand free' has no opponent-decides-exile-of-target-spell primitive. |
| Chronomantic Escape | `until your next turn, creatures can't attack you. exile ~ with 3 time counters on it.` | Blocked: no 'until your next turn, creatures can't attack you' duration effect and no spell self-exile-with-time-counters (suspend-style) primitive. |
| Cmdr. Troi, Outgoing Empath | `{t}: target opponent whose turn it is may cast a spell from their hand without paying its mana cost. if they do, you copy that spell. you may choose new targets for the copy. if they don't, you draw a card.` | Skipped: copying an opponent's free cast is too complex without a new primitive. |
| Concerted Effort | `at the beginning of each upkeep, creatures you control gain flying until end of turn if a creature you control has flying. the same is true for fear, first strike, double strike, landwalk, protection, trample, and vigilance.` | Blocked: needs copying the exact landwalk/protection qualities present among your creatures (per-quality keyword grants), which no group grant expresses. |
| Daniels, Temporal Agent | `{2}, put this card from your graveyard on the bottom of your library: you gain 2 life.` | Examined: ETB return is parser-claimed; missing primitive is an activated ability usable from the graveyard whose cost is 'put this card from your graveyard on the bottom of your library' (no such cost word in game/costs.py). |
| Dathon, His Heart Open | `whenever you cast an enchantment spell, draw a card. if it's a saga spell, ~ deals 2 damage to each opponent. \|\| {2}: choose a counter on target enchantment you control. put another counter of that kind on it. activate only as ...` | Blocked: '{2}: choose a counter on target enchantment you control, put another counter of that kind on it' (choose-a-counter-kind duplicate) has no primitive. |
| Deep Space 9 | `when ~ enters and at the beginning of your upkeep, exile the top 4 cards of your library. put all permanent cards exiled this way onto the battlefield.` | Blocked: 'put all permanent cards exiled this way onto the battlefield' needs an OR-of-permanent-types filter; return_all_exiled_with.card_types is AND (card_query all_types), so it can only be done as six sequential, non-simultaneous batches. |
| Extraction Integrant | `artifact creatures you control have menace and "whenever a creature blocks ~, that creature gets -1/-1 until end of turn."` | Blocked: grant_triggered_ability has no related_to_source param for 'whenever a creature blocks ~' and the BLOCKS related_filter has no 'controlled by the source's controller' key, so neither the granted nor the global form is exact. |
| Georgiou, Terran Emperor | `you don't lose the game for having 0 or less life. \|\| at the beginning of your end step, you lose 3 life and draw a card. then if your life total is 0 or less, create 10 1/1 red officer creature tokens.` | Examined: end-step half is expressible (lose_life, draw, if_else life_at_most 0 create 10 Officers); missing primitive is 'you don't lose the game for having 0 or less life' (a Phyrexian Unlife-style 704.5a-only exemption; `cant_lose_game` is blanket and would also stop poison/decking losses). |
| Gowron, Eager for Battle | `sacrifice another creature: ~ gains trample until end of turn. if you sacrificed a klingon this way, you draw a card and lose 1 life.` | Blocked: no condition for the subtype of a creature sacrificed as a cost. |
| Gwyndala, the Progeny | `when ~ enters, create a colorless equipment artifact token named neuroflux heirloom with "equipped creature gets +1/+1" and equip {2}. attach it to ~. \|\| {2}: each equipment token you control becomes a copy of target equipment ...` | Blocked: 'each Equipment token you control becomes a copy of target Equipment you control until end of turn' is a group become-copy; `become_copy_until_eot` / `become_copy_of_target_until_eot` (effects/registry.py) take one target permanent only. The ETB token (named Neuroflux Heirloom, granted equip {2}, attach to ~) was not probed further. |
| H.M.S. Bounty, Unlikely Timeship | `whenever ~ deals combat damage to a player, draw a card. if you control a whale and haven't begun an extra turn this game, take an extra turn after this 1.` | Blocked: no per-player 'has begun an extra turn this game' state. |
| Holo-Engineer | `if 1 or more tokens would be created under your control, that many 3/3 colorless illusion artifact creature tokens are created instead.` | Not authored: token-creation replacement ('that many 3/3 Illusion artifact creature tokens instead') has no whitelisted replacement type. |
| Hugh, First of Many | `artifact spells you cast have replicate {2}{u}.` | Blocked: replicate (RULE 702.56) does not exist in the engine (no keyword handler, no cast-time repeat-payment/copy-spell step; grep of game/ finds none) and there is no static 'spells you cast have <keyword>' grant for it (`granted_cast_keyword_instances` in continuous.py covers cast triggers only). |
| Kai Winn, Faithless Leader | `whenever an opponent casts a spell with the chosen name or activates an ability of a source with the chosen name, that player loses 3 life.` | Blocked: no trigger for 'activates an ability of a source with the chosen name'. |
| La Forge, Thoughtful as Ever | `{t}: for each permanent you control that you've put a counter on this turn, create a 1/1 blue faerie creature token with flying.` | Blocked: needs a `continuous.count_selector` selector 'distinct permanents you put a counter on this turn' (COUNTER events carry target_id and source_controller_id in `state.events_this_turn()`, but only the boolean conditions `you_placed_counter_on_creature_this_turn` / `counter_put_on_source_this_turn` read them) usable as `create_token` count; a shared-engine edit. |
| Lwaxana Troi, Charming Guest | `{2}, {t}: choose another target creature you control. for as long as ~ remains tapped, if a triggered ability of that creature triggers, that ability triggers an additional time.` | Blocked: `continuous._active_doublers` only scans `static_effects` of battlefield permanents (`TriggerDoublerEffect.subject` is a filter, not a chosen object) and never `state.floating_statics`; needs a floating trigger-doubler bound to one chosen creature with a `for_as_long_as` source-tapped duration (durations.py already has the duration). |
| Nog, Ambitious Cadet | `{1}: if ~ is a rogue, he becomes a ferengi scout with base power and toughness 3/4 and gains "whenever ~ becomes tapped, surveil 2." \|\| {3}: if ~ is a scout, he becomes a ferengi officer and gains "you may play lands from your ...` | Blocked: parts 1 and the type/P-T/extra-land half compose (`if_else` + `is_subtype`, `grant_until` rest_of_game with `type_change` set_creature_types/power/toughness, `grant_triggered_ability` TAPPED, `grant_static_ability` `extra_land_drop`), but 'you may play lands from your graveyard' cannot be granted: `graveyard_cast.active_graveyard_cast_grants` reads only `GraveyardCastPermissionEffect` objects in `static_effects`, not `_granted_static_abilities`/floating statics. Needs that scan widened. |
| Nyota Uhura, Communications | `as ~ enters, choose a number between 0 and 10. \|\| whenever an opponent casts a spell with mana value equal to the chosen number, you draw a card.` | Blocked: binding/core.py spell_characteristic_equals_chosen_number matches MV or power or toughness; an MV-only variant needs a shared-engine edit. |
| Peace in Our Time | `at the beginning of combat on each player's turn, that player may draw a card. if they do, they can't attack this turn and you put a peace counter on ~.` | Blocked: 'they can't attack this turn' for the active player has no primitive; no_attack_pairs_this_turn covers one (attacker, defender) pair, not every opponent. |
| Q, Stacking the Deck | `when ~ enters, shuffle your library, then exile cards from the top of your library until you exile a nonland card. that nonland card gains "exile a card from your hand: create a copy of this card. you may cast the copy. activat...` | Blocked: the exiled card must gain an activated ability usable from exile ('exile a card from your hand: create a copy of this card, you may cast the copy; only during your turn and only if this card is exiled'); `grant_activated_ability` (effects/registry.py) only reaches battlefield objects and activation_mixin has no activate-from-exile path for a granted ability. |
| Quark, Humble Proprietor | `you can't sacrifice treasure tokens.` | Examined: the Treasure upkeep trigger is parser-claimed; missing primitive is a static player/permanent-class prohibition 'can't sacrifice Treasure tokens' (only the per-object `cant_be_sacrificed_this_turn` flag exists). |
| Queen's Diamond | `{t}: choose a color. add 1 mana of that color for each charge counter on ~. spend this mana only to cast your commander.` | Blocked: mana abilities are parsed from raw text in game/mana_abilities.py; 'Choose a color. Add one mana of that color for each charge counter' (colour chosen per activation, amount from counters, commander-only restriction) is not a recognised shape, and an activated add_mana would not be a mana ability (RULE 605). |
| Rite of Oblivion | `as an additional cost to cast this spell, sacrifice a nonland permanent.` | Skipped: authored spec is complete except `additional_cost={"sacrifice": "nonland_permanent"}`, which `parser/oracle/spec.py` `_ADDITIONAL_COST_SACRIFICE_TYPES` rejects (the cost engine in `game/costs.py` already knows the word). Add it to that whitelist once the parser tree is free, then hand-author in minutes. |
| S.S. Botany Bay | `whenever ~ deals combat damage to a player, return each creature card you own exiled with it to the battlefield.` | Blocked: the tap ability's 'each opponent exiles a card from their graveyard' (`for_each` over `exile_hand_card` zone=graveyard) does not take `track_exiled_with`, so there is no 'creature card you own exiled with it' pool for the combat-damage `return_all_exiled_with`. Same missing flag as All Good Things... |
| Stonespeaker Crystal | `{2}, {t}, sacrifice ~: exile any number of target players' graveyards. draw a card.` | Examined: only `exile_target_graveyard` (single player target) exists; needs an 'any number of target players' graveyards' multi-target (0..N players) form. |
| Sulu, Heroic Helmsman | `~ stations spacecraft and crews vehicles as though his power were tripled.` | Blocked: 'crews as though power were tripled' is a multiplier; `GameEngine._crew_power_of` (engine/activation_mixin.py) only sums a flat `crew_power_bonus` count (Pilot idiom), and `_station_cost_choice`/`_resolve_station_cost` ignore any power bonus (station taps exactly one creature and uses raw power). Needs a multiplier kind plus station power accounting. |
| Sylvia Tilly, Joy of Discovery | `at the beginning of combat on your turn, you may pay {1} and exile a card from your graveyard. when you do, put a +1/+1 counter on target creature.` | Examined: authored spec ready (surveil + pay_cost_then then_trigger), but `RulesEngine._pay_player_cost` (game/rules/player_costs_mixin.py) ignores `ActivationCost.exile_from_graveyard`: pay_cost_then charges the mana and never exiles the card. Add an interactive graveyard-exile payment there, then author. |
| T'Pring, Never Parted | `when ~ enters, choose another target creature you control and target creature an opponent controls. you may have the chosen creatures fight each other. whenever a creature that fought this way dies this turn, you draw a card.` | Blocked: 'whenever a creature that fought this way dies this turn' tracks two creatures chosen by the same ETB; create_turn_trigger previous_subject captures only the first previous target. |
| The City on the Edge of Forever | `i — all artifacts and creatures phase out. create a 0/1 white human creature token with "permanents can't phase in." \|\| iii — sacrifice a creature token. if you do, you gain 5 life.` | Blocked: (1) no 'all artifacts and creatures phase out' (every player's): `phase_out_all_you_control` is the controller's only, `phase_out` is targeted; (2) `_step_untap` (engine/turn_loop_mixin.py) has no 'permanents can't phase in' check. |
| The Holodeck | `once during each of your turns, you may play a permanent card you own from outside the game or from your graveyard.` | Blocked, not a permanent non-goal (DEFERRED.md lists cross-game interactions only; `game/sideboard.py` implements RULE 400.11 outside-game cards): the sideboard permission (`sideboard_cast_permission`) is cast-only (no land play from outside the game in `can_play_land`) and has no per-turn limit shared with the graveyard half (`graveyard_cast_permission` once_per_turn is per granting permanent), so 'once during each of your turns, outside the game or graveyard' cannot be exact. |
| The Immortal Sun | `players can't activate planeswalkers' loyalty abilities.` | Blocked: 'players can't activate planeswalkers' loyalty abilities' has no prohibition primitive. |
| The Needs of the Many | `creatures you control gain hexproof and indestructible until end of turn. you gain hexproof until end of turn. prevent all damage that would be dealt to you this turn. exile ~.` | Blocked: 'you gain hexproof until end of turn' (a player) has no temporary form; player_hexproof is a battlefield static only (continuous.player_has_hexproof). Needs a PlayerShieldEffect-style hexproof marker. |
| Those Old Scientists | `ii — return up to 1 target artifact, instant, or sorcery card from your graveyard to your hand. \|\| iii — choose up to 2 target cards in graveyards. the owners of those cards shuffle them into their libraries.` | Blocked: ch. III needs a multi-player graveyard target, ch. II a multi-type graveyard target kind. |
| Unification | `i — the owner of up to 1 target creature draws 2 cards, then shuffles that creature into their library.` | Blocked: no 'shuffle target permanent into its owner's library' effect without Chaos Warp's reveal (shuffle_target_into_library_reveal_top) and no owner-draws recipient for it. |
| Vulcan Mind-Meld | `target opponent looks at the top card of your library, then exiles it face down. you look at the top 2 cards of their library, then exile them face down. for each card exiled this way, the player who exiled it may play it for a...` | Blocked: `impulsive_draw` (effects/registry.py factory) does not expose the class's `player`/`permission_player` params (its `library_of` only supports 'that_player' from a trigger event), so 'target opponent exiles the top card of MY library face down and may play it, and I exile their top two and may play them, any mana type' cannot be built; the any-mana-type rider (`mana_wildcard`) itself exists. |
| Võx, Child of the Collective | `when ~ enters and at the beginning of your first main phase, the next artifact creature spell and the next spacecraft spell you cast this turn have undaunted.` | Blocked: undaunted (RULE 702.125) does not exist in the engine (no keyword handler or cost reduction), and there is no 'next <type> spell you cast this turn has <keyword>' one-shot grant for it (`next_spell_flash_grants` is flash-only). |
| World at War | `after the second main phase this turn, there's an additional combat phase followed by an additional main phase. at the beginning of that combat, untap all creatures that attacked this turn.` | Blocked: extra_combat_phase (main_phase_too) inserts after the next end_combat (or the end of the turn when cast in main 2), not 'after the second main phase', and untap_at_beginning untaps creatures you control, not creatures that attacked this turn. |
| Genesis Device | `sacrifice any number of lands you control, then search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle.` | PAR-259 residue (v873): the ETB Planet search parses; needs a sacrifice-any-number-then-search-that-many primitive. |
| Warp Speed | `lands you control enter untapped.` | PAR-259 residue (v873): the search and the PAR-258 cost reduction parse; needs a static "enters untapped" replacement that overrides a land's own "enters tapped" (RULE 614.12 / 616.1 ordering). |

### Unsupported Rooms (reference only; not actionable queue entries)

These explain the remaining Room coverage denominator and must not be treated as implementation work: `Crude Abattoir // Unsavory Kitchen`, `Solitary Study // Endless Corridor`. Both return `NEVER_SUPPORTED` because their Alchemy halves are a permanent non-goal.
