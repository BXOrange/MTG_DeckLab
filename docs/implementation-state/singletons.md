# Singleton queue

**Current queue (2026-10-07, PARSER_VERSION 618): 181 distinct cards remain UNMODELED in 180 rows. Every listed card resolves in the local 35,099-card cache and is neither MODELED nor AUTHORED.** This is the remaining singleton queue, not the full unmodeled card pool; singleton/cluster membership has not been re-audited in this refresh.

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
| Blufferfish | Interactive true/false bluffing guess (an opponent states something, secretly notes true/false, you guess) | Needs a new `RulesEngine`/`continuations` primitive — no bluffing mechanic exists at all. |
| Smart Ass | Hidden-information reveal-or-not (opponent may reveal their hand to disprove a named card) | Same family as Blufferfish/Gollum below — each is its own distinct interactive shape, not one shared mechanic. |
| Gollum, Scheming Guide | Card-guessing minigame (opponent guesses land/nonland on a revealed top card) | Ditto — a third distinct hidden-information primitive. |
| Kamiz, Obscura Oculus | Connive, then choose *another* attacking creature with lesser power | The "lesser power" comparison against a just-connived creature has no composition yet. |
| Sewers of Estark | Branches on whether the target is attacking vs. blocking | An attacking-or-blocking conditional effect body, not a trigger condition. |
| Wedding Invitation | "If it's a vampire, it also gains lifelink" — a target-subtype-conditional keyword tail | A one-off conditional-grant-on-target shape. |
| Long River Lurker | ETB-targeted creature, then a delayed exile-and-return keyed to *that* creature dealing combat damage | The delayed trigger needs to reference an ETB-time RULE 115 target, not a self/previous-object referent. |
| Atomic Microsizer | Equip-trigger: choose a target, that creature becomes unblockable **and** animates to a fixed base P/T | The choose-then-animate compound on an equip trigger. |
| Zhuge Jin, Wu Strategist | "Activate only during your turn, before attackers are declared" | An activation-timing restriction tied to a combat sub-step, not just "your turn". |
| Secret Tunnel | "2 target creatures you control that share a creature type" | A same-type-as-each-other multi-target filter (cross-target constraint, not a fixed filter). |
| Open into Wonder | X target creatures, then a quoted-grant tail on "those creatures" | X-count multi-target combined with a group quoted-ability grant. |
| Unquenchable Fury | "Each minotaur can't be blocked this turn except by 2 or more creatures" | Mass/subtype-scoped unblockable with a *count*-based (not filter-based) except-by clause; `UnblockableEffect.selector` is a closed name enum, not filterable. |
| Chromium, the Mutable | "Becomes a human with base P/T 1/1, loses all abilities, and gains hexproof" | `_BASE_PT`-shaped, not `_ANIMATE_SELF`-shaped — a "loses all abilities" clause combined with a base-P/T set and a keyword grant in one sentence. |
| Writ of Passage | "Whenever enchanted creature attacks, if its power is 2 or less, `<effect>`" | An intervening-if reading the *attacker's own* power — the existing `attacked_player_has_most/lowest_life`-style gates all read the defender's state, a different subject. |
| Evie Frye | Loot (draw then discard), with a sub-trigger conditioned on the discarded card's type | The "when you discard a `<type>` card this way" sub-trigger inside a loot ability. |
| Mistford River Turtle | "Another target attacking **non-human** creature" | A subtype-*negation* qualifier on an attacking-creature target; no other cached card pairs "non-`<type>`" with this target shape. |
| Shrouded Serpent | "Defending player may pay `{4}`. If that player doesn't, `<effect>`" | A combat-trigger tax-or-else composition, distinct from the shipped attack-tax statics (this one gates a *different* effect on non-payment, not the attack itself). |
| Temmet, Vizier of Naktamun | "Target creature **token** you control" combined with pump + unblockable in one trigger | The "token" qualifier on this exact combined effect body; the one other cached card sharing "target creature token you control" (Kaya, Geist Hunter) is blocked on unrelated clauses too, so no real shared yield today. |
| Indoctrination Attendant | "If you do, create a 1/1 … token with toxic 1 **and** '`<quoted static ability>`'" | A printed-keyword-count-plus-quoted-ability token-creation compound; no token-creation handler combines both yet. |
| Goblin Ski Patrol | "Activate only once **and only if** you control a snow Mountain." — reversed "only once and only if" order (`_ACTIVATE_ONLY_IF_TRAILING_RE` only recognizes "only if `<cond>` [and only once]"), plus a "snow `<land type>`" control-count selector `_CONTROL_COUNT_SELECTORS` doesn't have | PAR-117's sacrifice-verb closure (PARSER_VERSION 417) unblocked the card's own sacrifice clause; this trailing activation-condition is the sole remaining gap, confirmed 1 SOLO/0 also-blocked via `parser_probe.py blocked "activate only once and only if"`. |
| Alora, Cheerful Scout / Alora, Cheerful Thief | "If you do, it perpetually gets +1/+1" / "a creature of your choice an opponent controls perpetually gets -1/-0" | Alchemy's `perpetually` is a documented engine non-goal (persistent cross-zone state, see `PARSER_LONG_TAIL.md`'s Alchemy row) — the rest of both cards (the delayed return, PAR-79's eighth increment) already parses. Two cards, one cause; not a ticket. |
| Blu, Mansion Prince | "Choose a Room card at random. Create a token that's a copy of 1 of its halves, then unlock it." | The Room/unlock subsystem plus a random-card-from-the-pool pick; no other cached card unlocks a Room this way (`parser_probe.py blocked "choose a room card at random"`: SOLO 1). |
| Lazav, Wearer of Faces | "You may have ~ become a copy of a creature card exiled with it until end of turn." | A self-copy of a *linked-exile* card (`GameObject.exiled_with_ids`) as a layer-1 copy effect; the "you sacrifice a Clue" trigger itself parses now, only this body is open. |
| Hurkyl, Master Wizard | "…reveal the top 5 cards of your library. For each card type among noncreature spells you've cast this turn, you may put a card of that type from among the revealed cards into your hand. Put the rest on the bottom …" | A per-card-type reveal-and-choose loop driven by the turn's cast-spell type history (`parser_probe.py blocked "for each card type among noncreature spells"`: SOLO 1). |
| Adverse Conditions | Its inline Eldrazi Scion token's quoted "Sacrifice this token: Add {C}" activated mana ability | PAR-84 now recognizes the preceding multi-target tap/next-untap sequence. The remaining full body is 1 SOLO/0 also-blocked (`parser_probe.py blocked "tap up to [0-9]+ target creatures\\. those creatures don.t untap"`); `CreateTokenEffect` has no generic inline-token activated-ability field, so this is a token-definition singleton, not a tap/untap parser family. |

The *clustered* residue these were sorted out of (2+ cards sharing one gap)
went to tickets in `docs/implementation-state/BACKLOG.md`, not to this file.

## Batch 2 — 2026-09-16 saved-deck coverage sweep

The rows below were **not** individually re-diagnosed with `parser_probe.py blocked` the way the queue above was — at this volume (1,020 cards across all 56 saved decks) that is a multi-session undertaking, tracked as an explicit follow-up rather than rushed. Instead every row passed a **mechanically equivalent, cache-wide check**: one `parse_oracle` pass over the full card cache (same `abstract_clause` normalization `commander_tail_report.py` uses) confirmed each card's unclaimed clause(s) have **no sibling anywhere in the cache** — a card with exactly one unclaimed clause unique cache-wide is listed plain; a card whose several unclaimed clauses are *each* individually unique is listed as a **compound gap** (all of them, not just one, would need a handler). A card with *any* clause that DOES cluster with another card was routed to a `PAR-*` ticket instead (PAR-99...PAR-114) or left for a future ticket batch — never listed here. Re-run the check before hand-authoring: a later batch can turn one of these into a two-card cluster, at which point promote it out per this file's own standing rule. Grouped by the saved deck each card was found uncovered in (its first non-cube deck, if it appears in more than one); `Commander Cube`/`cEDH staples`/`cEDH staples 2` cards with no non-cube deck are grouped under the cube itself. PARSER_VERSION 413.

**Re-evaluated 2026-09-29 at PARSER_VERSION 501, again 2026-09-30 at PARSER_VERSION 552** (whole file, all batches): 59 newly covered rows deleted, 17 gap cells updated to the card's current unclaimed clauses, deck counts recomputed. The exact-template test (below) still finds no shared clause, but a phrase-level sweep did: **~55 rows shared an *axis* with 4–31 other uncovered cards** and were promoted out into `BACKLOG.md` (PAR-136 blink at next end step, PAR-137 impulse draw, PAR-138 "N or more counters are put on", PAR-139 batch, MEC-106 Gift, MEC-107 expend) — their cards are named in those tickets. Re-run that sweep, not only the exact-template check, at the next re-evaluation: the exact-template check cannot see a shared *phrase* under different surrounding text.

### Commander Cube (146 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aerial Extortionist | Compound gap — `whenever <name> enters or deals combat damage to a player, exile up to <n> target nonland permanent. for as long as that card remains exiled, its owner may cast it.`; `whenever another player casts a spell from anywhere other than their hand, draw a card.` |  |
| Agadeem's Awakening // Agadeem, the Undercrypt | `return from your graveyard to the battlefield any number of target creature cards that each have a different mana value x or less.` |  |
| Anje's Ravager | `whenever <name> attacks, discard your hand, then draw <n> cards.` |  |
| Archfiend of Spite | `whenever a source an opponent controls deals damage to <name>, that source's controller loses that much life unless they sacrifice that many permanents of their choice.` |  |
| Aven Interrupter | Compound gap — `spells your opponents cast from graveyards or from exile cost <cost> more to cast.`; `when <name> enters, exile target spell. it becomes plotted.` |  |
| Azra Oddsmaker | `at the beginning of combat on your turn, you may discard a card. if you do, choose a creature. whenever that creature deals combat damage to a player this turn, you draw <n> cards.` |  |
| Azure Fleet Admiral | `<name> can't be blocked by creatures the monarch controls.` |  |
| Barad-dûr | `<cost>, <cost>: amass orcs x. activate only if a creature died this turn.` |  |
| Barrin, Tolarian Archmage | `at the beginning of your end step, if a permanent was put into your hand from the battlefield this turn, draw a card.` |  |
| Battle for Bretagard | `iii — choose any number of artifact tokens and/or creature tokens you control with different names. for each of them, create a token that's a copy of it.` |  |
| Benevolent Offering | Compound gap — `choose an opponent. you and that player each create <n> <n>/<n> white spirit creature tokens with flying.`; `choose an opponent. you gain <n> life for each creature you control and that player gains <n> life for each creature they control.` |  |
| Black Sun's Twilight | `up to <n> target creature gets -x/-x until end of turn. if x is <n> or more, return a creature card with mana value x or less from your graveyard to the battlefield tapped.` |  |
| Blanchwood Prowler | `when <name> enters, mill <n> cards. you may put a land card from among the cards milled this way into your hand. if you don't, put a +<n>/+<n> counter on <name>.` |  |
| Blast-Furnace Hellkite | `creatures attacking your opponents have double strike.` |  |
| Bloodtithe Harvester | `<cost>, sacrifice <name>: target creature gets -x/-x until end of turn, where x is twice the number of blood tokens you control. activate only as a sorcery.` |  |
| Brallin, Skyshark Rider | `<cost>: target shark gains trample until end of turn.` |  |
| Call to the Netherworld | `return target black creature card from your graveyard to your hand.` |  |
| Cat Collector | `whenever you gain life for the first time during each of your turns, create a <n>/<n> white cat creature token.` |  |
| Celestine, the Living Saint | `at the beginning of your end step, return target creature card with mana value x or less from your graveyard to the battlefield, where x is the amount of life you gained this turn.` |  |
| Cemetery Desecrator | Compound gap — `when <name> enters or dies, exile another card from a graveyard. when you do, choose <n> —`; `• remove x counters from target permanent, where x is the mana value of the exiled card.`; `• target creature an opponent controls gets -x/-x until end of turn, where x is the mana value of the exiled card.` |  |
| Chainer, Nightmare Adept | Compound gap — `discard a card: you may cast a creature spell from your graveyard this turn. activate only once each turn.`; `whenever a nontoken creature you control enters, if you didn't cast it from your hand, it gains haste until your next turn.` |  |
| Chainsaw | `equipped creature gets +x/+<n>, where x is the number of rev counters on <name>.` |  |
| Champion of Lambholt | `creatures with power less than <name>'s power can't block creatures you control.` |  |
| Cleaver Skaab | `<cost>, <cost>, sacrifice another zombie: create <n> tokens that are copies of the sacrificed creature.` |  |
| Cool but Rude | Compound gap — `when this class becomes level <n>, search your library for a card, put it into your hand, shuffle, then discard a card at random.`; `whenever you discard a card, this class deals <n> damage to each opponent.` |  |
| Crown of Gondor | `when a legendary creature you control enters, if there is no monarch, you become the monarch.` |  |
| Custodi Lich | `whenever you become the monarch, target player sacrifices a creature of their choice.` |  |
| Daretti, Rocketeer Engineer | `whenever <name> enters or attacks, choose target artifact card in your graveyard. you may sacrifice an artifact. if you do, return the chosen card to the battlefield.` |  |
| Dark Salvation | `target player creates x <n>/<n> black zombie creature tokens, then up to <n> target creature gets -<n>/-<n> until end of turn for each zombie that player controls.` |  |
| Dauntless Scrapbot | `when <name> enters, exile each opponent's graveyard. create a lander token.` |  |
| Disciple of Freyalise // Garden of Freyalise | `when <name> enters, you may sacrifice another creature. if you do, you gain x life and draw x cards, where x is that creature's power.` |  |
| Doctor Doom, King of Latveria | `at the beginning of combat on your turn, target villain you control gains menace until end of turn. it connives.` |  |
| Don & Leo, Problem Solvers | `at the beginning of your end step, exile up to <n> target artifact you control and up to <n> target creature you control. then return them to the battlefield under their owners' control.` |  |
| Draconic Muralists | `when <name> dies, you may search your library for a dragon card, reveal it, put it into your hand, then shuffle.` |  |
| Dragon Broodmother | `at the beginning of each upkeep, create a <n>/<n> red and green dragon creature token with flying and devour <n>.` |  |
| Dragonborn Champion | `whenever a source you control deals <n> or more damage to a player, draw a card.` |  |
| Dragonspark Reactor | `<cost>, sacrifice <name>: it deals damage equal to the number of charge counters on it to target player and that much damage to up to <n> target creature.` |  |
| Draining Whelk | `when <name> enters, counter target spell. put x +<n>/+<n> counters on <name>, where x is that spell's mana value.` |  |
| Dusk Mangler | Compound gap — `as an additional cost to cast this spell, sacrifice a creature, discard a card, or pay <n> life.`; `when <name> enters, each opponent sacrifices a creature of their choice, discards a card, and loses <n> life.` |  |
| Echocasting Symposium | `target player creates a token that's a copy of target creature you control.` |  |
| Edgar's Awakening | `when you discard this card, you may pay <cost>. when you do, return target creature card from your graveyard to your hand.` |  |
| Elenda's Hierophant | `when <name> dies, create x <n>/<n> white vampire creature tokens with lifelink, where x is its power.` |  |
| Elenda, Saint of Dusk | `as long as your life total is greater than your starting life total, <name> gets +<n>/+<n> and has menace. <name> gets an additional +<n>/+<n> as long as your life total is at least <n> greater than your starting life total.` |  |
| Elesh Norn // The Argent Etchings | `whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller loses <n> life unless they pay <cost>.` |  |
| Emberwilde Captain | `whenever an opponent attacks you while you're the monarch, <name> deals damage to that player equal to the number of cards in their hand.` |  |
| Emeria's Call // Emeria, Shattered Skyclave | `create <n> <n>/<n> white angel warrior creature tokens with flying. non-angel creatures you control gain indestructible until your next turn.` |  |
| Empty the Laboratory | `sacrifice x zombies, then reveal cards from the top of your library until you reveal a number of zombie creature cards equal to the number of zombies sacrificed this way. put those cards onto the battlefield and the rest on the bottom of your library in a random order.` |  |
| Eris, Roar of the Storm | `this spell costs <cost> less to cast for each different mana value among instant and sorcery cards in your graveyard.` |  |
| Ezuri, Claw of Progress | Compound gap — `at the beginning of combat on your turn, put x +<n>/+<n> counters on another target creature you control, where x is the number of experience counters you have.`; `whenever a creature you control with power <n> or less enters, you get an experience counter.` |  |
| Fallen Shinobi | `whenever <name> deals combat damage to a player, that player exiles the top <n> cards of their library. until end of turn, you may play those cards without paying their mana costs.` |  |
| Fatestitcher | `<cost>: you may tap or untap another target permanent.` |  |
| Fear of Impostors | `when <name> enters, counter target spell. its controller manifests dread.` |  |
| Filigree Vector | `when <name> enters, put a +<n>/+<n> counter on each of any number of target creatures and a charge counter on each of any number of target artifacts.` |  |
| Foe-Razer Regent | `whenever a creature you control fights, put <n> +<n>/+<n> counters on it at the beginning of the next end step.` |  |
| Geralf, Visionary Stitcher | `<cost>, <cost>, sacrifice another nontoken creature: create an x/x blue zombie creature token, where x is the sacrificed creature's toughness.` |  |
| Geralf, the Fleshwright | Compound gap — `whenever a zombie you control enters, put a +<n>/+<n> counter on it for each other zombie that entered the battlefield under your control this turn.`; `whenever you cast a spell during your turn other than your first spell that turn, create a <n>/<n> blue and black zombie rogue creature token.` |  |
| Gilraen, Dúnedain Protector | `<cost>, <cost>: exile another target creature you control. you may return that card to the battlefield under its owner's control. if you don't, at the beginning of the next end step, return that card to the battlefield under its owner's control with a vigilance counter and a lifelink counter on it.` |  |
| Gisa, the Hellraiser | Compound gap — `skeletons and zombies you control get +<n>/+<n> and have menace.`; `whenever you commit a crime, create <n> tapped <n>/<n> blue and black zombie rogue creature tokens. this ability triggers only once each turn.` |  |
| Glimmer Lens | `whenever equipped creature and at least <n> other creature attack, draw a card.` |  |
| Glimpse the Impossible | `exile the top <n> cards of your library. you may play those cards this turn. at the beginning of the next end step, if any of those cards remain exiled, put them into your graveyard, then create a <n>/<n> colorless eldrazi spawn creature token for each card put into your graveyard this way. those tokens have <name>` |  |
| Gumdrop Poisoner // Tempt with Treats | `when <name> enters, up to <n> target creature gets -x/-x until end of turn, where x is the amount of life you gained this turn.` |  |
| Hagra Mauling // Hagra Broodpit | `this spell costs <cost> less to cast if an opponent controls no basic lands.` |  |
| Havengul Lich | `<cost>: you may cast target creature card in a graveyard this turn. when you cast it this turn, <name> gains all activated abilities of that card until end of turn.` |  |
| Highcliff Felidar | `when <name> enters, for each opponent, choose a creature with the greatest power among creatures that player controls. destroy those creatures.` |  |
| Highway Robbery | `you may discard a card or sacrifice a land. if you do, draw <n> cards.` |  |
| Ignite the Future | `exile the top <n> cards of your library. until the end of your next turn, you may play those cards. if this spell was cast from a graveyard, you may play cards this way without paying their mana costs.` |  |
| Improvisation Capstone | `exile cards from the top of your library until you exile cards with total mana value <n> or greater. you may cast any number of spells from among them without paying their mana costs.` |  |
| Increasing Devotion | `create <n> <n>/<n> white human creature tokens. if this spell was cast from a graveyard, create <n> of those tokens instead.` |  |
| Invasion of Tarkir // Defiant Thundermaw | `when <name> enters, reveal any number of dragon cards from your hand. when you do, <name> deals x plus <n> damage to any other target, where x is the number of cards revealed this way.` |  |
| Ironsoul Enforcer | `whenever <name> or a commander you control attacks alone, return target artifact card from your graveyard to the battlefield.` |  |
| Jalira, Master Polymorphist | `<cost>, <cost>, sacrifice another creature: reveal cards from the top of your library until you reveal a nonlegendary creature card. put that card onto the battlefield and the rest on the bottom of your library in a random order.` |  |
| Jinnie Fay, Jetmir's Second | `if you would create <n> or more tokens, you may instead create that many <n>/<n> green cat creature tokens with haste or that many <n>/<n> green dog creature tokens with vigilance.` |  |
| Jugan Defends the Temple // Remnant of the Rising Star | `i — create a <n>/<n> green human monk creature token with <name>` |  |
| Juvenile Mist Dragon | `when <name> enters, for each opponent, tap up to <n> target creature that player controls. each of those creatures doesn't untap during its controller's next untap step.` |  |
| Kitesail Larcenist | `when <name> enters, for each player, choose up to <n> other target artifact or creature that player controls. for as long as <name> remains on the battlefield, the chosen permanents become treasure artifacts with <name> and lose all other abilities.` |  |
| Lluwen, Imperfect Naturalist | `when <name> enters, mill <n> cards, then you may put a creature or land card from among the milled cards on top of your library.` |  |
| Losheel, Clockwork Scholar | `prevent all combat damage that would be dealt to attacking artifact creatures you control.` |  |
| Loyal Unicorn | `at the beginning of combat on your turn, if you control your commander, prevent all combat damage that would be dealt to creatures you control this turn. other creatures you control gain vigilance until end of turn.` |  |
| Ludevic, Necrogenius // Olag, Ludevic's Hubris | `<cost>, exile x creature cards from your graveyard: transform <name>. x can't be <n>. activate only as a sorcery.` |  |
| Malevolent Rumble | `reveal the top <n> cards of your library. you may put a permanent card from among them into your hand. put the rest into your graveyard. create a <n>/<n> colorless eldrazi spawn creature token with <name>` |  |
| Mana Sculpt | `counter target spell. if you control a wizard, add an amount of <cost> equal to the amount of mana spent to cast that spell at the beginning of your next main phase.` |  |
| Masked Vandal | `when <name> enters, you may exile a creature card from your graveyard. if you do, exile target artifact or enchantment an opponent controls.` |  |
| Master of Death | `at the beginning of your upkeep, if this card is in your graveyard, you may pay <n> life. if you do, return it to your hand.` |  |
| Meteor Blast | `<name> deals <n> damage to each of x targets.` |  |
| Moonveil Regent | Compound gap — `when <name> dies, it deals x damage to any target, where x is the number of colors among permanents you control.`; `whenever you cast a spell, you may discard your hand. if you do, draw a card for each of that spell's colors.` |  |
| Moria Scavenger | `<cost>, discard a card: draw a card. if the discarded card was a creature card, amass orcs <n>.` |  |
| Nahiri's Resolve | `at the beginning of your end step, exile any number of nontoken artifacts and/or creatures you control. return those cards to the battlefield under their owner's control at the beginning of your next upkeep.` |  |
| Old Rutstein | `when <name> enters and at the beginning of your upkeep, mill a card. if a land card is milled this way, create a treasure token. if a creature card is milled this way, create a <n>/<n> green insect creature token. if a noncreature, nonland card is milled this way, create a blood token.` |  |
| Organ Hoarder | `when <name> enters, look at the top <n> cards of your library, then put <n> of them into your hand and the rest into your graveyard.` |  |
| Osgir, the Reconstructor | `<cost>, <cost>, exile an artifact card with mana value x from your graveyard: create <n> tokens that are copies of the exiled card. activate only as a sorcery.` |  |
| Party Thrasher | `noncreature spells you cast from exile have convoke.` |  |
| Peel from Reality | `return target creature you control and target creature you don't control to their owners' hands.` |  |
| Phelia, Exuberant Shepherd | `whenever <name> attacks, exile up to <n> other target nonland permanent. at the beginning of the next end step, return that card to the battlefield under its owner's control. if it entered under your control, put a +<n>/+<n> counter on <name>.` |  |
| Phyrexian Delver | `when <name> enters, return target creature card from your graveyard to the battlefield. you lose life equal to that card's mana value.` |  |
| Predatory Rampage | `creatures you control get +<n>/+<n> until end of turn. each creature your opponents control blocks this turn if able.` |  |
| Prosper, Tome-Bound | Compound gap — `mystic arcanum — at the beginning of your end step, exile the top card of your library. until the end of your next turn, you may play that card.`; `pact boon — whenever you play a card from exile, create a treasure token.` |  |
| Puppet Master, String Puller | `whenever you attack, goad target creature an opponent controls. it can't block this turn.` |  |
| Queen Allenal of Ruadach | `if <n> or more creature tokens would be created under your control, those tokens plus a <n>/<n> white soldier creature token are created instead.` |  |
| Ravenous Gigantotherium | `when <name> enters, it deals x damage divided as you choose among up to x target creatures, where x is its power. each of those creatures deals damage equal to its power to <name>.` |  |
| Ravenous Robots | `<cost>, <cost>: creature tokens you control gain haste until end of turn.` |  |
| Reconstruct History | `return up to <n> target artifact card, up to <n> target enchantment card, up to <n> target instant card, up to <n> target sorcery card, and up to <n> target planeswalker card from your graveyard to your hand.` |  |
| Red Dragon | `fire breath — when <name> enters, it deals <n> damage to each opponent.` |  |
| Rise of the Witch-king | `each player sacrifices a creature of their choice. if you sacrificed a creature this way, you may return another permanent card from your graveyard to the battlefield.` |  |
| Sarevok's Tome | `<cost>, <cost>: exile cards from the top of your library until you exile a nonland card. you may cast that card without paying its mana cost. activate only if you've completed a dungeon.` |  |
| Scampering Surveyor | `when <name> enters, search your library for a basic land card or cave card, put it onto the battlefield tapped, then shuffle.` |  |
| Scavenged Brawler | `<cost>, exile this card from your graveyard: choose target creature. put <n> +<n>/+<n> counters, a flying counter, a vigilance counter, a trample counter, and a lifelink counter on that creature. activate only as a sorcery.` |  |
| Sea Gate Restoration // Sea Gate, Reborn | `draw cards equal to the number of cards in your hand plus <n>. you have no maximum hand size for the rest of the game.` |  |
| Seasoned Dungeoneer | `whenever you attack, target attacking cleric, rogue, warrior, or wizard gains protection from creatures until end of turn. it explores.` |  |
| Seasoned Pyromancer | `when <name> enters, discard <n> cards, then draw <n> cards. for each nonland card discarded this way, create a <n>/<n> red elemental creature token.` |  |
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
| Teleportation Circle | `at the beginning of your end step, exile up to <n> target artifact or creature you control, then return that card to the battlefield under its owner's control.` |  |
| The Eternal Wanderer | Compound gap — `+<n>: exile up to <n> target artifact or creature. return that card to the battlefield under its owner's control at the beginning of that player's next end step.`; `no more than <n> creature can attack <name> each combat.`; `−<n>: for each player, choose a creature that player controls. each player sacrifices all creatures they control not chosen this way.` |  |
| The Raven Man | `at the beginning of each end step, if a player discarded a card this turn, create a <n>/<n> black bird creature token with flying and <name>` |  |
| Thousand Moons Smithy // Barracks of the Thousand | `at the beginning of your first main phase, you may tap <n> untapped artifacts and/or creatures you control. if you do, transform <name>.` |  |
| Thrakkus the Butcher | `whenever <name> attacks, double the power of each dragon you control until end of turn.` |  |
| Three Steps Ahead | Compound gap — `+ <cost> — counter target spell.`; `+ <cost> — create a token that's a copy of target artifact or creature you control.`; `+ <cost> — draw <n> cards, then discard a card.` |  |
| Thrull Parasite | `<cost>, pay <n> life: remove a counter from target nonland permanent.` |  |
| Tivash, Gloom Summoner | `at the beginning of your end step, if you gained life this turn, you may pay x life, where x is the amount of life you gained this turn. if you do, create an x/x black demon creature token with flying.` |  |
| Toby, Beastie Befriender | `when <name> enters, create a <n>/<n> white beast creature token with <name>` |  |
| Tom Bombadil | Compound gap — `as long as there are <n> or more lore counters among sagas you control, <name> has hexproof and indestructible.`; `whenever the final chapter ability of a saga you control resolves, reveal cards from the top of your library until you reveal a saga card. put that card onto the battlefield and the rest on the bottom of your library in a random order. this ability triggers only once each turn.` |  |
| Tomb of Horrors Adventurer | `whenever you cast your second spell each turn, copy it. if you've completed a dungeon, copy that spell twice instead. you may choose new targets for the copies.` |  |
| Transmogrifying Wand | `<cost>, <cost>, remove a charge counter from <name>: destroy target creature. its controller creates a <n>/<n> white ox creature token. activate only as a sorcery.` |  |
| Twilight Prophet | `at the beginning of your upkeep, if you have the city's blessing, reveal the top card of your library and put it into your hand. each opponent loses x life and you gain x life, where x is that card's mana value.` |  |
| Ugin, the Spirit Dragon | Compound gap — `−<n>: you gain <n> life, draw <n> cards, then put up to <n> permanent cards from your hand onto the battlefield.`; `−x: exile each permanent with mana value x or less that's <n> or more colors.` |  |
| Unexplained Absence | `for each player, exile up to <n> target nonland permanent that player controls. for each permanent exiled this way, its controller cloaks the top card of their library.` |  |
| Unholy Heat | `<name> deals <n> damage instead if there are <n> or more card types among cards in your graveyard.` |  |
| Virtue of Strength // Garenbrig Growth | `if you tap a basic land for mana, it produces <n> times as much of that mana instead.` |  |
| Voracious Fell Beast | `when <name> enters, each opponent sacrifices a creature of their choice. create a food token for each creature sacrificed this way.` |  |
| Warden of the Grove | `whenever another nontoken creature you control enters, it endures x, where x is the number of counters on <name>.` |  |
| White Plume Adventurer | `at the beginning of each opponent's upkeep, untap a creature you control. if you've completed a dungeon, untap all creatures you control instead.` |  |
| Wildfire Devils | `when <name> enters and at the beginning of your upkeep, choose a player at random. that player exiles an instant or sorcery card from their graveyard. copy that card. you may cast the copy without paying its mana cost.` |  |
| Windswift Slice | `target creature you control deals damage equal to its power to target creature you don't control. create a number of <n>/<n> green elf warrior creature tokens equal to the amount of excess damage dealt this way.` |  |
| Y'shtola Rhul | `at the beginning of your end step, exile target creature you control, then return it to the battlefield under its owner's control. then if it's the first end step of the turn, there is an additional end step after this step.` |  |
| Zameck Guildmage | `<cost>: this turn, each creature you control enters with an additional +<n>/+<n> counter on it.` |  |
| Zombie Apocalypse | `return all zombie creature cards from your graveyard to the battlefield tapped, then destroy all humans.` |  |

### Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck (9 cards)

| Card | Gap | Notes |
| --- | --- | --- |

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
| Lobe Lobber | Granted "{T}: ~ deals 1 damage to target player or planeswalker. Roll a 6-sided die. On a 5 or higher, untap it." | A die-roll-gated untap; the RULE 706 dice subsystem exists (MEC-75), but this is the only card whose text gates an untap on a roll result. |
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
