# Singleton queue

**Queue after the PAR-239 close on 2026-11-09: 135 rows remain.** The 2026-11-02 audit at PARSER_VERSION 819 found 155 rows; completed cards are removed after runtime validation. Grouped rows and duplicate names remain historical queue entries, not a distinct-card coverage count. Short names refer to Nick Fury, Spymaster; Lonis, Cryptozoologist; Surrak, Elusive Hunter; and Neheb, Dreadhorde Champion.

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

### Commander Cube (17 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Rise of the Witch-king | `each player sacrifices a creature of their choice. if you sacrificed a creature this way, you may return another permanent card from your graveyard to the battlefield.` |  |
| Seasoned Dungeoneer | `whenever you attack, target attacking cleric, rogue, warrior, or wizard gains protection from creatures until end of turn. it explores.` |  |
| Shadowgrange Archfiend | `when <name> enters, each opponent sacrifices a creature with the greatest power among creatures they control. you gain life equal to the greatest power among creatures sacrificed this way.` |  |
| Sheoldred // The True Scriptures | `when <name> enters, each opponent sacrifices a nontoken creature or planeswalker of their choice.` |  |
| Simic Manipulator | `<cost>, remove <n> or more +<n>/+<n> counters from <name>: gain control of target creature with power less than or equal to the number of +<n>/+<n> counters removed this way.` |  |
| Spinerock Tyrant | `whenever you cast an instant or sorcery spell with a single target, you may copy it. if you do, those spells gain wither. you may choose new targets for the copy.` |  |
| The Eternal Wanderer | Compound gap — `+<n>: exile up to <n> target artifact or creature. return that card to the battlefield under its owner's control at the beginning of that player's next end step.`; `no more than <n> creature can attack <name> each combat.`; `−<n>: for each player, choose a creature that player controls. each player sacrifices all creatures they control not chosen this way.` |  |
| Thousand Moons Smithy // Barracks of the Thousand | `at the beginning of your first main phase, you may tap <n> untapped artifacts and/or creatures you control. if you do, transform <name>.` |  |
| Tivash, Gloom Summoner | `at the beginning of your end step, if you gained life this turn, you may pay x life, where x is the amount of life you gained this turn. if you do, create an x/x black demon creature token with flying.` |  |
| Tom Bombadil | Compound gap — `as long as there are <n> or more lore counters among sagas you control, <name> has hexproof and indestructible.`; `whenever the final chapter ability of a saga you control resolves, reveal cards from the top of your library until you reveal a saga card. put that card onto the battlefield and the rest on the bottom of your library in a random order. this ability triggers only once each turn.` |  |
| Tomb of Horrors Adventurer | `whenever you cast your second spell each turn, copy it. if you've completed a dungeon, copy that spell twice instead. you may choose new targets for the copies.` |  |
| Ugin, the Spirit Dragon | Compound gap — `−<n>: you gain <n> life, draw <n> cards, then put up to <n> permanent cards from your hand onto the battlefield.`; `−x: exile each permanent with mana value x or less that's <n> or more colors.` |  |
| Unexplained Absence | `for each player, exile up to <n> target nonland permanent that player controls. for each permanent exiled this way, its controller cloaks the top card of their library.` |  |
| Virtue of Strength // Garenbrig Growth | `if you tap a basic land for mana, it produces <n> times as much of that mana instead.` |  |
| Wildfire Devils | `when <name> enters and at the beginning of your upkeep, choose a player at random. that player exiles an instant or sorcery card from their graveyard. copy that card. you may cast the copy without paying its mana cost.` |  |


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

## Batch 7 — 2026-10-19 PAR-132 close-out (PARSER_VERSION 692)

Sized with `parser_probe.py blocked` at v691–692: each row's cards share a phrase but not a body, so none forms a cluster. Re-run the check before hand-authoring.

| Card | Gap | Notes |
| --- | --- | --- |
| Decoy Gambit, Mega Flare, Tolarian Contempt | `for each opponent, choose up to one target … that player controls` + chosen-set body | Per-round chosen-set referent; three different bodies. |
| Alpha Brawl, Deputy of Detention | prior-target group bodies | Three distinct shapes. |
| Windshaper Planetar, Portal Manipulator, Arni Metalbrow, Nick Fury, Shark Shredder, Summoner's Grimoire, Noble Ox | `enters … attacking` / reselect the attacked player | Eight distinct bodies. |
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
| Ghostfire | "~ is colorless" inside a spell body | |


## Batch 9 — 2026-10-20 PAR-175 close-out (PARSER_VERSION 712)

Sized during PAR-175 M4b: "the permanent(s) for which …" occurs on this card only. See `Done_Backend.md` "Clause linkage across a sequence (PAR-175)".

| Card | Gap | Notes |
| --- | --- | --- |
| Scrambleverse | "for each nonland permanent, choose a player at random. then each player gains control of each permanent for which they were chosen. untap those permanents." | Needs a random player per permanent and control changes by that assignment; no engine primitive for a per-object random choice yet. |


## Batch 10 — 2026-10-20 PAR-176 close-out (PARSER_VERSION 713)

Each card's "Activate only …" sentence is otherwise claimed; only its condition has no `static_conditions` primitive. See `Done_Backend.md` "\"Activate only …\" restriction sentences (PAR-176)".

| Card | Gap | Notes |
| --- | --- | --- |
| Sea Troll | "only if ~ blocked or was blocked by a blue creature this turn" | Per-turn block history with the blocker's color. |
| Blitzball | an opponent was dealt combat damage by a legendary creature this turn | Per-turn damage history by source type. |
| Kongming's Contraptions | "only if you've been attacked this step" | Per-step attack history. |

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

### Battles (5 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Invasion of Alara // Awaken the Maelstrom | `when ~ enters, exile cards from the top of your library until you exile 2 nonland cards with mana value 4 or less. you may cast 1 of those 2 cards without paying its mana cost. put 1 of them into your hand. then put the other cards exiled this way on the bottom of your library in a random order.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Arcavios // Invocation of the Founders | `when ~ enters, search your library, graveyard, and/or outside the game for an instant or sorcery card you own, reveal it, and put it into your hand. if you search your library this way, shuffle.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Gobakhan // Lightshield Array | `when ~ enters, look at target opponent's hand. you may exile a nonland card from it. for as long as that card remains exiled, its owner may play it. a spell cast this way costs {2} more to cast.` | Current unclaimed clauses; singleton/cluster check pending. |
| Invasion of Tarkir // Defiant Thundermaw | `when ~ enters, reveal any number of dragon cards from your hand. when you do, ~ deals x plus 2 damage to any other target, where x is the number of cards revealed this way.` | Current unclaimed clauses; singleton/cluster check pending. |
| The Battle of Dragon Brothers // Fate Reforged | `when ~ enters, choose bolas or ugin.`; `• bolas — destroy all creatures.`; `• ugin — manifest the top 3 cards of your library.` | Current unclaimed clauses; singleton/cluster check pending. |

### Rooms (3 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Central Elevator // Promising Stairs | `when you unlock this door, search your library for a room card that doesn't have the same name as a room you control, reveal it, put it into your hand, then shuffle.` | Current unclaimed clauses; singleton/cluster check pending. |
| Charred Foyer // Warped Space | `once each turn, you may pay {0} rather than pay the mana cost for a spell you cast from exile.` | Current unclaimed clauses; singleton/cluster check pending. |
| Walk-In Closet // Forgotten Cellar | `when you unlock this door, you may cast spells from your graveyard this turn, and if a card would be put into your graveyard from anywhere this turn, exile it instead.` | Current unclaimed clauses; singleton/cluster check pending. |

### Controlled-return residue (PAR-225 close, PARSER_VERSION 824)

| Card | Gap | Notes |
| --- | --- | --- |
| Infernal Harvest | `as an additional cost to cast this spell, return X swamps you control to their owner's hand.` | Only card with an X-count return cost; `return_pick` is a one-permanent cost and the X plumbing is sacrifice-specific. Hand-author. |
| Barrel Down Sokenzan | `deals damage equal to twice the number of mountains returned this way` | "Equal to N times the number returned" body; the `returned` this-way pool exists (v824), the multiplier does not. |

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
| Fated Clash, Silver Scrutiny, Quantum Reduction, Timely Ward, Tegwyll's Scouring | "you may cast this spell as though it had flash if <state>" | Conditions not yet parsed (attacking+blocking creature, X ≤ 3, teamwork, targets a commander, tap-three-fliers cost); promote to a ticket if two share a condition. |

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
| Hero of Bretagard, Ranar the Ever-Watchful | `whenever 1 or more cards are put into exile from your hand or a spell or ability you control exiles 1 or more permanents from the battlefield` | Shared pair, both blocked by other clauses as well; promote together once those land. |
| The Heron Moon | body: release counter, at 13 or more sacrifice it and cast a copy of Emrakul, the Promised End | Head parses (v833 exile batch). |
| Ketramose, the New Dawn | `~ can't attack or block unless there are 7 or more cards in exile` | Head parses (v833). |
| Breeches, Brazen Plunderer | body: `exile the top card of each of those opponents' libraries ...` | Head parses (v833 damage batch). |
| Screeching Scorchbeast | body: `you may create that many ... do this only once each turn` | Head and `nonland_count` exist (v832). |
| Sand Scout | body: the `red, green, and white` token | Head parses (v832). |
| Flummoxed Cyclops | body: `can't block this combat` | Head parses (v831). |

### Attachment-head residue (PAR-234 close, PARSER_VERSION 834)

| Card | Gap | Notes |
| --- | --- | --- |
| Curse of Echoes | body: `each other player may copy that spell and may choose new targets` | Head (enchanted player casts) parses since v834. |
| Maddening Hex | body: `roll a d6 ... then attach ~ to another 1 of your opponents chosen at random` | Head parses since v834. |
| Grievous Wound | static: `enchanted player can't gain life` | `enchanted player is dealt damage` head parses since v834. |
| Archnemesis | `whenever you attack enchanted player` and `whenever a player attacks you, you may attach ~ to that player` | Actor-you form is excluded in `player_event_head`. |
| Kestia, the Cultivator | `whenever an enchanted creature or enchantment creature you control attacks` | Disjunctive attached-or-type subject. |
| Eriette, the Beguiler | Aura becomes attached to a nonland permanent an opponent controls with mana value at most that Aura's | Attach-host filter with a comparison to the Aura. |

### Graveyard-head residue (PAR-235 close, PARSER_VERSION 835)

| Card | Gap | Notes |
| --- | --- | --- |
| Dredging Claw | `whenever a creature enters from your graveyard, you may attach ~ to it` | Entry with a from-zone filter (graveyard). |
| Golgari Brownscale | `when this card is put into your hand from your graveyard` | Self graveyard-to-hand move. `RETURNED_TO_HAND` with `from_zone` exists since ENG-54 (v842); only the self `this card` head with a graveyard origin is missing. |

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
| Archimandrite | cost: `tap 3 untapped advisors, artificers, and/or monks you control` | Subtype-union tap cost. |
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

### Combat-status target residue (PAR-246 close, PARSER_VERSION 841)

| Card | Gap | Notes |
| --- | --- | --- |
| Sonar Strike | `~ deals 4 damage to target attacking, blocking, or tapped creature. you gain 3 life if you control a bat.` | Three-state adjective union plus a conditional rider. |
| Spirit Flare | `tap target untapped creature you control. if you do, it deals damage equal to its power to target attacking or blocking creature an opponent controls.` | Two-target "if you do" chain; Flashback with a life payment. |
| Unerring Sling | cost: `{3}, {t}, tap an untapped creature you control`; effect: damage equal to the tapped creature's power to target attacking or blocking creature with flying | Needs the tapped-cost creature's power as the amount. |

### Zone-arrival residue (ENG-54 close, PARSER_VERSION 842)

| Card | Gap | Notes |
| --- | --- | --- |
| Wan Shi Tong, All-Knowing | `when ~ enters, target nonland permanent's owner puts it into their library second from the top or on the bottom.` | The owner chooses the position; the "1 or more cards are put into a library" head already parses (ENG-54). |

### Living metal back-face residue (MEC-137 close, PARSER_VERSION 843)

Back faces of Living metal cards (RULE 702.161a, the Vehicle side is already an artifact creature on its controller's turn). Each carries its own unclaimed clause and ends in "convert ~". Re-run `parser_probe.py blocked` before picking one up: the shared "convert ~" tail and MEC-137's `additional_beginning_phase` / `event_player` primitives may have turned some into a cluster.

| Card | Gap | Notes |
| --- | --- | --- |
| Blitzwing, Cruel Tormentor // Blitzwing, Adaptive Assailant | `at the beginning of combat on your turn, choose flying or indestructible at random. ~ gains that ability until end of turn.` | Needs a random keyword choice. |
| Flamewar, Brash Veteran // Flamewar, Streetwise Operative | `whenever ~ deals combat damage to a player, exile that many cards from the top of your library face down. put an intel counter on each of them. convert ~.` | Face-down exile with a counter on each card. |
| Megatron, Tyrant // Megatron, Destructive Force | `whenever ~ attacks, you may sacrifice another artifact. when you do, ~ deals damage equal to the sacrificed artifact's mana value to target creature. if excess damage would be dealt to that creature this way, instead that damage is dealt to that creature's controller and you convert ~.` | Excess-damage redirect; see PAR-243 for the excess-damage event gap. |
| Optimus Prime, Hero // Optimus Prime, Autobot Leader | `whenever you attack, bolster 2. the chosen creature gains trample until end of turn. when that creature deals combat damage to a player this turn, convert ~.` | Bolster's chosen creature is the referent of the delayed trigger. |

### Escape rider residue (PAR-239 close, PARSER_VERSION 844)

Cards next to the plain "escapes with N counters" shape, each probed SOLO on 1. Re-run `parser_probe.py blocked` on the clause before authoring.

| Card | Gap | Notes |
| --- | --- | --- |
| Charred Graverobber | `when ~ enters, return target outlaw card from your graveyard to your hand.` | Its `escapes with` line is claimed; the `outlaw` card target filter is the only blocker. |
| Pharika's Spawn | `~ escapes with 2 +1/+1 counters on it. when it enters this way, each opponent sacrifices a non-gorgon creature of their choice.` | Needs an Escape-only reflexive trigger next to the counters. |
| Polukranos, Unchained | `~ enters with 6 +1/+1 counters on it. it escapes with 12 +1/+1 counters on it instead.` | The Escape amount replaces the printed enters-with amount. |
| Skyway Robber | `~ escapes with "whenever ~ deals combat damage to a player, you may cast an artifact, instant, or sorcery spell from among cards exiled with ~ without paying its mana cost."` | Escape grants a quoted ability over the cards exiled with it. |
| Tizerus Charger | `~ escapes with your choice of a +1/+1 counter or a flying counter on it.` | Counter-kind choice as it enters (RULE 614.1c). |

### Unsupported Rooms (reference only; not actionable queue entries)

These explain the remaining Room coverage denominator and must not be treated as implementation work: `Crude Abattoir // Unsavory Kitchen`, `Solitary Study // Endless Corridor`. Both return `NEVER_SUPPORTED` because their Alchemy halves are a permanent non-goal.
