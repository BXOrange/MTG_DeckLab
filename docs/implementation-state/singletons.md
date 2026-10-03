# Singleton queue

**Current queue (2026-10-03, PARSER_VERSION 594): 607 distinct cards remain UNMODELED in 608 rows.** The Squirreled Away batch removed 19 covered rows after the PARSER_VERSION 591 queue audit. Rechecked every listed card against the local 35,095-card cache using `parse_oracle` and `card_registry.is_registered` (MODELED or AUTHORED counts as covered); removed 223 covered rows, refreshed Batch 2 gap cells and recomputed its deck counts. The Alora row contains two cards. This is the remaining singleton queue, not the full unmodeled card pool; singleton/cluster membership has not been re-audited in this refresh.

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
| First Responder | Untargeted "return another creature you control to hand, **then** put counters on ~ equal to that creature's power" | Related to Niambi's targeted-return-then-measure shape (PAR-98, closed) but a third, distinct shape: "then" (not "if you do") sequencing, and a magnitude reading the just-returned creature's *power* rather than gating on success. |
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


### Abzan Armor - Tarkir: Dragonstorm Commander (18 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Assault Formation | `<cost>: target creature with defender can attack this turn as though it didn't have defender.` |  |
| Baldin, Century Herdmaster | `whenever <name> attacks, up to <n> hundred target creatures each get +<n>/+x until end of turn, where x is the number of cards in your hand.` |  |
| Betor, Ancestor's Voice | `at the beginning of your end step, put a number of +<n>/+<n> counters on up to <n> other target creature you control equal to the amount of life you gained this turn. return up to <n> target creature card with mana value less than or equal to the amount of life you lost this turn from your graveyard to the battlefield.` | Also uncovered in: Commander Cube |
| Canopy Gargantuan | `at the beginning of your upkeep, put a number of +<n>/+<n> counters on each other creature you control equal to that creature's toughness.` |  |
| Colfenor's Urn | `at the beginning of the end step, if <n> or more cards have been exiled with <name>, sacrifice it. if you do, return those cards to the battlefield under their owner's control.` |  |
| Expel the Interlopers | `choose a number between <n> and <n>. destroy all creatures with power greater than or equal to the chosen number.` |  |
| Jaws of Defeat | `whenever a creature you control enters, target opponent loses life equal to the difference between that creature's power and its toughness.` |  |
| Reunion of the House | `return any number of target creature cards with total power <n> or less from your graveyard to the battlefield. exile <name>.` |  |
| Sidar Kondo of Jamuraa | `creatures your opponents control without flying or reach can't block creatures with power <n> or less.` |  |
| Staff of Compleation | `<cost>, pay <n> life: destroy target permanent you own.` |  |
| Tip the Scales | `sacrifice a creature. when you do, all creatures get -x/-x until end of turn, where x is the sacrificed creature's toughness.` |  |
| Towering Titan | `<name> enters with x +<n>/+<n> counters on it, where x is the total toughness of other creatures you control.` |  |
| Tree of Redemption | `<cost>: exchange your life total with <name>'s toughness.` |  |
| Wakestone Gargoyle | `<cost>: creatures you control with defender can attack this turn as though they didn't have defender.` |  |
| Walking Bulwark | `<cost>: until end of turn, target creature with defender gains haste, can attack as though it didn't have defender, and assigns combat damage equal to its toughness rather than its power. activate only as a sorcery.` |  |
| Wall of Limbs | `<cost>, sacrifice <name>: target player loses x life, where x is <name>'s power.` |  |
| Wall of Reverence | `at the beginning of your end step, you may gain life equal to the power of target creature you control.` | Also uncovered in: Hope to the last |
| Weathered Sentinels | `<name> can attack players who attacked you during their last turn as though it didn't have defender.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |


### Animated Army - Bloomburrow Commander (12 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Alchemist's Talent | Compound gap — `treasures you control have <name>`; `whenever you cast a spell, if mana from a treasure was spent to cast it, this class deals damage equal to that spell's mana value to each opponent.` |  |
| Bello, Bard of the Brambles | `during your turn, each non-equipment artifact and non-aura enchantment you control with mana value <n> or greater is a <n>/<n> elemental creature in addition to its other types and has indestructible, haste, and <name>` |  |
| Brightcap Badger // Fungus Frolic | `each fungus and saproling you control has <name>` | Also uncovered in: Commander Cube |
| Decimate | `destroy target artifact, target creature, target enchantment, and target land.` | Also uncovered in: Limit Break - Final Fantasy Commander |
| Evercoat Ursine | `whenever <name> deals combat damage to a player, if there are cards exiled with it, you may play <n> of them without paying its mana cost.` |  |
| Goreclaw, Terror of Qal Sisma | Compound gap — `creature spells you cast with power <n> or greater cost <cost> less to cast.`; `whenever <name> attacks, each creature you control with power <n> or greater gets +<n>/+<n> and gains trample until end of turn.` | Also uncovered in: Commander Cube |
| Grothama, All-Devouring | Compound gap — `other creatures have <name>`; `when <name> leaves the battlefield, each player draws cards equal to the amount of damage dealt to <name> this turn by sources they controlled.` |  |
| Mosswort Bridge | `<cost>, <cost>: you may play the exiled card without paying its mana cost if creatures you control have total power <n> or greater.` | Also uncovered in: Jump Scare! - Duskmourn: House of Horror Commander, Riveteer Rampage - New Capenna Commander, Temur Roar - Tarkir: Dragonstorm Commander |
| Prosperous Bandit | `whenever <name> deals combat damage to a player, create that many tapped treasure tokens.` |  |
| Rain of Riches | `the first spell you cast each turn that mana from a treasure was spent to cast has cascade.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Thickest in the Thicket | Compound gap — `at the beginning of your end step, draw <n> cards if you control the creature with the greatest power or tied for the greatest power.`; `when <name> enters, put x +<n>/+<n> counters on target creature, where x is that creature's power.` |  |
| Wildsear, Scouring Maw | `enchantment spells you cast from your hand have cascade.` |  |


### Commander Cube (157 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aerial Extortionist | Compound gap — `whenever <name> enters or deals combat damage to a player, exile up to <n> target nonland permanent. for as long as that card remains exiled, its owner may cast it.`; `whenever another player casts a spell from anywhere other than their hand, draw a card.` |  |
| Agadeem's Awakening // Agadeem, the Undercrypt | `return from your graveyard to the battlefield any number of target creature cards that each have a different mana value x or less.` |  |
| All Is Dust | `each player sacrifices all permanents they control that are <n> or more colors.` |  |
| Anje's Ravager | `whenever <name> attacks, discard your hand, then draw <n> cards.` |  |
| Archfiend of Spite | `whenever a source an opponent controls deals damage to <name>, that source's controller loses that much life unless they sacrifice that many permanents of their choice.` |  |
| Archon of Cruelty | `whenever <name> enters or attacks, target opponent sacrifices a creature or planeswalker of their choice, discards a card, and loses <n> life. you draw a card and gain <n> life.` |  |
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
| Death Baron | `skeletons you control and other zombies you control get +<n>/+<n> and have deathtouch.` |  |
| Diregraf Colossus | `<name> enters with a +<n>/+<n> counter on it for each zombie card in your graveyard.` |  |
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
| Fall from Favor | `enchanted creature doesn't untap during its controller's untap step unless that player is the monarch.` |  |
| Fallen Shinobi | `whenever <name> deals combat damage to a player, that player exiles the top <n> cards of their library. until end of turn, you may play those cards without paying their mana costs.` |  |
| Fateful Absence | `destroy target creature or planeswalker. its controller investigates.` |  |
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
| Monstrous Onslaught | `<name> deals x damage divided as you choose among any number of target creatures, where x is the greatest power among creatures you control as you cast this spell.` |  |
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
| Pink Horror | `when <name> dies, create <n> <n>/<n> blue and red demon horror creature tokens named blue horror with <name>` |  |
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
| Sephara, Sky's Blade | `you may pay <cost> and tap <n> untapped creatures you control with flying rather than pay this spell's mana cost.` |  |
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
| Undead Butler | `when <name> dies, you may exile it. when you do, return target creature card from your graveyard to your hand.` |  |
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
| Zul Ashur, Lich Lord | `<cost>: you may cast target zombie creature card from your graveyard this turn.` |  |


### Counter Blitz - Final Fantasy Commander (26 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Auron, Venerated Guardian | `whenever <name> attacks, put a +<n>/+<n> counter on it. when you do, exile target creature defending player controls with power less than <name>'s power until <name> leaves the battlefield.` |  |
| Blitzball Stadium | `<cost>, <cost>: until end of turn, target creature gains <name> and it can't be blocked this turn.` |  |
| Chocobo Knights | `whenever you attack, creatures you control with counters on them gain double strike until end of turn.` |  |
| Endless Detour | `the owner of target spell, nonland permanent, or card in a graveyard puts it on their choice of the top or bottom of their library.` |  |
| Fight Rigging | `at the beginning of combat on your turn, put a +<n>/+<n> counter on target creature you control. then if you control a creature with power <n> or greater, you may play the exiled card without paying its mana cost.` | Also uncovered in: Commander Cube |
| Forge of Heroes | `<cost>: choose target commander that entered this turn. put a +<n>/+<n> counter on it if it's a creature and a loyalty counter on it if it's a planeswalker.` |  |
| Gatta and Luzzu | `when <name> enters, choose target creature you control. if damage would be dealt to that creature this turn, prevent that damage and put that many +<n>/+<n> counters on it.` |  |
| Generous Patron | `whenever you put <n> or more counters on a creature you don't control, draw a card.` |  |
| Kimahri, Valiant Guardian | `at the beginning of combat on your turn, put a +<n>/+<n> counter on <name> and tap target creature an opponent controls. then you may have <name> become a copy of that creature, except its name is <name> and it has vigilance and this ability.` |  |
| Lord Jyscal Guado | `at the beginning of each end step, if you put a counter on a creature this turn, investigate.` |  |
| Lulu, Stern Guardian | `whenever an opponent attacks you, choose target creature attacking you. put a stun counter on that creature.` |  |
| Maester Seymour | Compound gap — `<cost>: monstrosity x, where x is the number of counters among creatures you control.`; `at the beginning of combat on your turn, put a number of +<n>/+<n> counters equal to <name>'s power on another target creature you control.` |  |
| Protection Magic | `put a shield counter on each of up to <n> target creatures.` | Also uncovered in: Hope to the last |
| Rampant Rejuvenator | `when <name> dies, search your library for up to x basic land cards, where x is <name>'s power, put them onto the battlefield, then shuffle.` |  |
| Rikku, Resourceful Guardian | Compound gap — `<cost>, <cost>: move a counter from target creature an opponent controls onto target creature you control. activate only as a sorcery.`; `whenever you put <n> or more counters on a creature, until end of turn, that creature can't be blocked by creatures your opponents control.` | Also uncovered in: Commander Cube |
| Scholar of New Horizons | `<cost>, remove a counter from a permanent you control: search your library for a plains card and reveal it. if an opponent controls more lands than you, you may put that card onto the battlefield tapped. if you don't put the card onto the battlefield, put it into your hand. then shuffle.` |  |
| Sin, Unending Cataclysm | Compound gap — `as <name> enters, remove all counters from any number of artifacts, creatures, and enchantments. <name> enters with x +<n>/+<n> counters on it, where x is twice the number of counters removed this way.`; `when <name> dies, put its counters on target creature you control, then shuffle this card into its owner's library.` |  |
| Summon: Ixion | `i — aerospark — exile target creature an opponent controls until this saga leaves the battlefield.` |  |
| Summon: Magus Sisters | Compound gap — `i, ii, iii — choose <n> at random —`; `• combine powers! — put <n> +<n>/+<n> counters on target creature.`; `• defense! — put a shield counter on target creature. you gain <n> life.`; `• fight! — <name> fights up to <n> target creature an opponent controls.` |  |
| Summon: Valefor | `i — sonic wings — each opponent chooses a creature with the greatest mana value among creatures they control. return those creatures to their owners' hands.` |  |
| Summon: Yojimbo | Compound gap — `i — exile target artifact, enchantment, or tapped creature an opponent controls.`; `ii, iii — until your next turn, creatures can't attack you unless their controller pays <cost> for each of those creatures.`; `iv — create x treasure tokens, where x is the number of opponents who control a creature with power <n> or greater.` |  |
| Summoner's Sending | `at the beginning of your end step, you may exile target creature card from a graveyard. if you do, create a <n>/<n> white spirit creature token with flying. put a +<n>/+<n> counter on it if the exiled card's mana value is <n> or greater.` |  |
| Tidus, Yuna's Guardian | `at the beginning of combat on your turn, you may move a counter from target creature you control onto a second target creature you control.` |  |
| Together Forever | `<cost>: choose target creature with a counter on it. when that creature dies this turn, return that card to its owner's hand.` | Also uncovered in: Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck |
| Tromell, Seymour's Butler | `<cost>, <cost>: proliferate x times, where x is the number of nontoken creatures you control that entered this turn.` |  |
| Wakka, Devoted Guardian | `at the beginning of your end step, if a counter was put on <name> this turn, put a +<n>/+<n> counter on each other creature you control.` |  |


### Counter Intelligence - Edge of Eternities Commander Deck (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Death Toll - Duskmourn: House of Horror Commander (18 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Arachnogenesis | `create x <n>/<n> green spider creature tokens with reach, where x is the number of creatures attacking you. prevent all combat damage that would be dealt this turn by non-spider creatures.` |  |
| Carrion Grub | `<name> gets +x/+<n>, where x is the greatest power among creature cards in your graveyard.` |  |
| Cemetery Tampering | `at the beginning of your upkeep, you may mill <n> cards. then if there are twenty or more cards in your graveyard, you may play the exiled card without paying its mana cost.` |  |
| Convert to Slime | Compound gap — `destroy up to <n> target artifact, up to <n> target creature, and up to <n> target enchantment.`; `then if there are <n> or more card types among cards in your graveyard, create an x/x green ooze creature token, where x is the total mana value of permanents destroyed this way.` |  |
| Deadbridge Chant | `at the beginning of your upkeep, choose a card at random in your graveyard. if it's a creature card, put it onto the battlefield. otherwise, put it into your hand.` |  |
| Deluge of Doom | `all creatures get -x/-x until end of turn, where x is the number of card types among cards in your graveyard.` |  |
| Demonic Covenant | Compound gap — `at the beginning of your end step, create a <n>/<n> black demon creature token with flying, then mill <n> cards. if <n> cards that share all their card types were milled this way, sacrifice <name>.`; `whenever <n> or more demons you control attack a player, you draw a card and lose <n> life.` |  |
| Grapple with the Past | `mill <n> cards, then you may return a creature or land card from your graveyard to your hand.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Grist, the Hunger Tide | Compound gap — `+<n>: create a <n>/<n> black and green insect creature token, then mill a card. if an insect card was milled this way, put a loyalty counter on <name> and repeat this process.`; `as long as <name> isn't on the battlefield, it's a <n>/<n> insect creature in addition to its other types.` | Also uncovered in: Commander Cube |
| Into the Pit | `you may cast spells from the top of your library by sacrificing a nonland permanent in addition to paying their other costs.` |  |
| Moldgraf Monstrosity | `when <name> dies, exile it, then return <n> creature cards at random from your graveyard to the battlefield.` |  |
| Rendmaw, Creaking Nest | `when <name> enters and whenever you play a card with <n> or more card types, each player creates a tapped <n>/<n> black bird creature token with flying. the tokens are goaded for the rest of the game.` |  |
| Titania, Nature's Force | `you may play forests from your graveyard.` |  |
| Ursine Monstrosity | `at the beginning of combat on your turn, mill a card and choose an opponent at random. <name> attacks that player this combat if able. until end of turn, <name> gains indestructible and gets +<n>/+<n> for each card type among cards in your graveyard.` |  |
| Whip of Erebos | `<cost>, <cost>: return target creature card from your graveyard to the battlefield. it gains haste. exile it at the beginning of the next end step. if it would leave the battlefield, exile it instead of putting it anywhere else. activate only as a sorcery.` |  |
| Whispersilk Cloak | `equipped creature can't be blocked and has shroud.` |  |
| Winter, Cynical Opportunist | `at the beginning of your end step, you may exile any number of cards from your graveyard with <n> or more card types among them. if you do, put a permanent card from among them onto the battlefield with a finality counter on it.` |  |
| Wrenn and Seven | `<n>: put any number of land cards from your hand onto the battlefield tapped.` |  |


### Endless Punishment - Duskmourn: House of Horror Commander (23 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Barbflare Gremlin | `whenever a player taps a land for mana, if <name> is tapped, that player adds <n> mana of any type that land produced. then that land deals <n> damage to that player.` |  |
| Braids, Arisen Nightmare | `at the beginning of your end step, you may sacrifice an artifact, creature, enchantment, land, or planeswalker. if you do, each opponent may sacrifice a permanent of their choice that shares a card type with it. for each opponent who doesn't, that player loses <n> life and you draw a card.` | Also uncovered in: World Shaper - Edge of Eternities Commander Deck |
| Combustible Gearhulk | `when <name> enters, target opponent may have you draw <n> cards. if the player doesn't, you mill <n> cards, then <name> deals damage to that player equal to the total mana value of those cards.` | Also uncovered in: Living Energy - Aetherdrift Commander, Revival Trance - Final Fantasy Commander |
| Enchanter's Bane | `at the beginning of your end step, target enchantment deals damage equal to its mana value to its controller unless that player sacrifices it.` |  |
| Fear of Burning Alive | `whenever a source you control deals noncombat damage to an opponent, if there are <n> or more card types among cards in your graveyard, <name> deals that amount of damage to target creature that player controls.` |  |
| Florian, Voldaren Scion | `at the beginning of each of your postcombat main phases, look at the top x cards of your library, where x is the total amount of life your opponents lost this turn. exile <n> of those cards and put the rest on the bottom of your library in a random order. you may play the exiled card this turn.` |  |
| Grab the Prize | `draw <n> cards. if the discarded card wasn't a land card, <name> deals <n> damage to each opponent.` |  |
| Kardur, Doomscourge | `when <name> enters, until your next turn, creatures your opponents control attack each combat if able and attack a player other than you if able.` |  |
| Kederekt Parasite | `whenever an opponent draws a card, if you control a red permanent, you may have <name> deal <n> damage to that player.` |  |
| Mask of Griselbrand | `whenever equipped creature dies, you may pay x life, where x is its power. if you do, draw x cards.` |  |
| Massacre Girl | `when <name> enters, each other creature gets -<n>/-<n> until end of turn. whenever a creature dies this turn, each creature other than <name> gets -<n>/-<n> until end of turn.` |  |
| Mogis, God of Slaughter | `at the beginning of each opponent's upkeep, <name> deals <n> damage to that player unless they sacrifice a creature of their choice.` |  |
| Persistent Constrictor | `at the beginning of each opponent's upkeep, they lose <n> life and you put a -<n>/-<n> counter on up to <n> target creature they control.` |  |
| Rakdos, Lord of Riots | Compound gap — `creature spells you cast cost <cost> less to cast for each <n> life your opponents have lost this turn.`; `you can't cast <name> unless an opponent lost life this turn.` |  |
| Sadistic Shell Game | `starting with the next opponent in turn order, each player chooses a creature you don't control. destroy the chosen creatures.` |  |
| Spiked Corridor // Torture Pit | `when you unlock this door, create <n> <n>/<n> red devil creature tokens with <name>` |  |
| Spinerock Knoll | `<cost>, <cost>: you may play the exiled card without paying its mana cost if an opponent was dealt <n> or more damage this turn.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Star Athlete | `whenever <name> attacks, choose up to <n> target nonland permanent. its controller may sacrifice it. if they don't, <name> deals <n> damage to that player.` |  |
| Suspended Sentence | `destroy target creature an opponent controls. that player loses <n> life. exile <name> with <n> time counters on it.` |  |
| The Lord of Pain | `whenever a player casts their first spell each turn, choose another target player. <name> deals damage equal to that spell's mana value to the chosen player.` |  |
| Valgavoth, Harrower of Souls | `whenever an opponent loses life for the first time during each of their turns, put a +<n>/+<n> counter on <name> and draw a card.` |  |
| Vial Smasher the Fierce | `whenever you cast your first spell each turn, choose an opponent at random. vial smasher deals damage equal to that spell's mana value to that player or a planeswalker that player controls.` |  |
| Witch's Clinic | `<cost>, <cost>: target commander gains lifelink until end of turn.` |  |


### Eternal Might - Aetherdrift Commander (17 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Accursed Duneyard | `<cost>, <cost>: regenerate target shade, skeleton, specter, spirit, vampire, wraith, or zombie.` |  |
| Champion of Wits | `when <name> enters, you may draw cards equal to its power. if you do, discard <n> cards.` |  |
| Commence the Endgame | `draw <n> cards, then amass zombies x, where x is the number of cards in your hand.` |  |
| Corpse Augur | `when <name> dies, you draw x cards and you lose x life, where x is the number of creature cards in target player's graveyard.` |  |
| Dread Summons | `each player mills x cards. for each creature card put into a graveyard this way, you create a tapped <n>/<n> black zombie creature token.` |  |
| Forgotten Creation | `at the beginning of your upkeep, you may discard all the cards in your hand. if you do, draw that many cards.` |  |
| Gate to the Afterlife | `<cost>, <cost>, sacrifice <name>: search your graveyard, hand, and/or library for a card named god-pharaoh's gift and put it onto the battlefield. if you search your library this way, shuffle. activate only if there are <n> or more creature cards in your graveyard.` |  |
| Gempalm Polluter | `when you cycle this card, you may have target player lose life equal to the number of zombies on the battlefield.` |  |
| Lord of the Accursed | `<cost>, <cost>: all zombies gain menace until end of turn.` |  |
| Lost Monarch of Ifnir | Compound gap — `at the beginning of your second main phase, if a player was dealt combat damage by a zombie this turn, mill <n> cards, then you may return a creature card from your graveyard to your hand.`; `other zombies you control have afflict <n>.` |  |
| On Wings of Gold | `creatures you control that are zombies and/or tokens get +<n>/+<n> and have flying.` |  |
| Priest of the Crossing | `at the beginning of each end step, put x +<n>/+<n> counters on each creature you control, where x is the number of creatures that died under your control this turn.` |  |
| Prophet of the Scarab | `when <name> enters, draw cards equal to the number of zombies you control or the number of zombie cards in your graveyard, whichever is greater.` | Also uncovered in: Commander Cube |
| Rot Hulk | `when <name> enters, return up to x target zombie cards from your graveyard to the battlefield, where x is the number of opponents you have.` | Also uncovered in: Commander Cube |
| Unholy Grotto | `<cost>, <cost>: put target zombie card from your graveyard on top of your library.` |  |
| Vizier of Many Faces | `you may have <name> enter as a copy of any creature on the battlefield, except if <name> was embalmed, the token has no mana cost, it's white, and it's a zombie in addition to its other types.` |  |
| Wizened Mentor | `whenever an opponent activates an ability of a permanent that isn't a mana ability, you create a <n>/<n> white zombie creature token. this ability triggers only once each turn.` |  |


### Family Matters - Bloomburrow Commander (15 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aetherize | `return all attacking creatures to their owner's hand.` |  |
| Bident of Thassa | `<cost>, <cost>: creatures your opponents control attack this turn if able.` |  |
| Boss's Chauffeur | `<name> enters with a number of +<n>/+<n> counters on it equal to <n> plus the number of other creatures you control.` |  |
| Cut a Deal | `each opponent draws a card, then you draw a card for each opponent who drew a card this way.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Inferno Titan | `whenever <name> enters or attacks, it deals <n> damage divided as you choose among <n>, <n>, or <n> targets.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Jacked Rabbit | `whenever <name> attacks, create a number of <n>/<n> white rabbit creature tokens equal to <name>'s power.` |  |
| Junk Winder | `whenever a token you control enters, tap target nonland permanent an opponent controls. it doesn't untap during its controller's next untap step.` |  |
| Murmuration | `at the beginning of your end step, for each spell you've cast this turn, create a <n>/<n> blue bird creature token with flying named storm crow.` |  |
| Pollywog Prodigy | `whenever an opponent casts a noncreature spell with mana value less than <name>'s power, draw a card.` |  |
| Rapid Augmenter | `whenever another creature you control with base power <n> enters, it gains haste until end of turn.` |  |
| Shield Broker | `when <name> enters, put a shield counter on target noncommander creature you don't control. you gain control of that creature for as long as it has a shield counter on it.` |  |
| Stolen by the Fae | `return target creature with mana value x to its owner's hand. you create x <n>/<n> blue faerie creature tokens with flying.` |  |
| Storm of Souls | `return all creature cards from your graveyard to the battlefield. each of them is a <n>/<n> spirit with flying in addition to its other types. exile <name>.` |  |
| Tetsuko Umezawa, Fugitive | `creatures you control with power or toughness <n> or less can't be blocked.` |  |
| Zinnia, Valley's Voice | Compound gap — `<name> gets +x/+<n>, where x is the number of other creatures you control with base power <n>.`; `creature spells you cast gain offspring <cost> as you cast them.` |  |


### Goblins (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Hope to the last (19 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Ajani, Strength of the Pride | Compound gap — `<n>: if you have at least <n> life more than your starting life total, exile <name> and each artifact and creature your opponents control.`; `−<n>: create a <n>/<n> white cat soldier creature token named <name>'s pridemate with <name>` |  |
| Angel of Destiny | Compound gap — `at the beginning of your end step, if you have at least <n> life more than your starting life total, each player <name> attacked this turn loses the game.`; `whenever a creature you control deals combat damage to a player, you and that player each gain that much life.` |  |
| Beacon of Immortality | `double target player's life total. shuffle <name> into its owner's library.` |  |
| Exemplar of Light | `whenever you put <n> or more +<n>/+<n> counters on <name>, draw a card. this ability triggers only once each turn.` | Also uncovered in: Commander Cube |
| Gold-Forged Thopteryx | `each legendary permanent you control has ward <cost>.` |  |
| Honor the Fallen | `exile all creature cards from all graveyards. you gain <n> life for each card exiled this way.` |  |
| Hope Estheim | `at the beginning of your end step, each opponent mills x cards, where x is the amount of life you gained this turn.` |  |
| Memory Erosion | `whenever an opponent casts a spell, that player mills <n> cards.` |  |
| Minas Tirith | `<cost>, <cost>: draw a card. activate only if you attacked with <n> or more creatures this turn.` | Also uncovered in: Commander Cube |
| Nykthos Paragon | `whenever you gain life, you may put that many +<n>/+<n> counters on each creature you control. do this only once each turn.` | Also uncovered in: Commander Cube |
| Resplendent Angel | `<cost>: until end of turn, <name> gets +<n>/+<n> and gains lifelink.` | Also uncovered in: Commander Cube |
| Restoration Magic | Compound gap — `• cura — <cost> — target permanent gains hexproof and indestructible until end of turn. you gain <n> life.`; `• curaga — <cost> — permanents you control gain hexproof and indestructible until end of turn. you gain <n> life.`; `• cure — <cost> — target permanent gains hexproof and indestructible until end of turn.` |  |
| Riverchurn Monument | Compound gap — `<cost>, <cost>: any number of target players each mill <n> cards.`; `exhaust — <cost>, <cost>: any number of target players each mill cards equal to the number of cards in their graveyard.` |  |
| Shabraz, the Skyshark | `<cost>: target human gains flying until end of turn.` |  |
| Speaker of the Heavens | `<cost>: create a <n>/<n> white angel creature token with flying. activate only if you have at least <n> life more than your starting life total and only as a sorcery.` |  |
| Sphinx of the Revelation | `<cost>, <cost>, pay x <cost>: draw x cards.` |  |
| Starfield Shepherd | `when <name> enters, search your library for a basic plains card or a creature card with mana value <n> or less, reveal it, put it into your hand, then shuffle.` |  |
| The Water Crystal | Compound gap — `<cost>, <cost>: each opponent mills cards equal to the number of cards in your hand.`; `if an opponent would mill <n> or more cards, they mill that many cards plus <n> instead.` |  |
| Well of Lost Dreams | `whenever you gain life, you may pay <cost>, where x is less than or equal to the amount of life you gained. if you do, draw x cards.` |  |


### Hydranten (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Jeskai Striker - Tarkir: Dragonstorm Commander (6 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Baral and Kari Zev | `whenever you cast your first instant or sorcery spell each turn, you may cast a spell with lesser mana value that shares a card type with it from your hand without paying its mana cost. if you don't, create first mate ragavan, a legendary <n>/<n> red monkey pirate creature token. it gains haste until end of turn.` |  |
| Curse of Opulence | `whenever enchanted player is attacked, create a gold token. each opponent attacking that player does the same.` |  |
| Expansion // Explosion | `copy target instant or sorcery spell with mana value <n> or less. you may choose new targets for the copy.` |  |
| Transcendent Dragon | `when <name> enters, if you cast it, counter target spell. if that spell is countered this way, exile it instead of putting it into its owner's graveyard, then you may cast it without paying its mana cost.` |  |
| Transforming Flourish | `destroy target artifact or creature you don't control. if that permanent is destroyed this way, its controller exiles cards from the top of their library until they exile a nonland card, then they may cast that card without paying its mana cost.` |  |
| Velomachus Lorehold | `whenever <name> attacks, look at the top <n> cards of your library. you may cast an instant or sorcery spell with mana value less than or equal to <name>'s power from among them without paying its mana cost. put the rest on the bottom of your library in a random order.` |  |


### Jump Scare! - Duskmourn: House of Horror Commander (19 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Arixmethes, Slumbering Isle | `as long as <name> has a slumber counter on it, it's a land.` |  |
| Curator Beastie | `colorless creatures you control enter with <n> additional +<n>/+<n> counters on them.` |  |
| Deathmist Raptor | `whenever a permanent you control is turned face up, you may return this card from your graveyard to the battlefield face up or face down.` |  |
| Disorienting Choice | `for each opponent, choose up to <n> target artifact or enchantment that player controls. for each permanent chosen this way, its controller may exile it. then if <n> or more of the chosen permanents are still on the battlefield, you search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle.` |  |
| Experimental Lab // Staff Room | `when you unlock this door, manifest dread, then put <n> +<n>/+<n> counters and a trample counter on that creature.` |  |
| Ezuri's Predation | `for each creature your opponents control, create a <n>/<n> green phyrexian beast creature token. each of those tokens fights a different <n> of those creatures.` |  |
| Growing Dread | `whenever you turn a permanent face up, put a +<n>/+<n> counter on it.` |  |
| Kheru Spellsnatcher | `when <name> is turned face up, counter target spell. if that spell is countered this way, exile it instead of putting it into its owner's graveyard. you may cast that card without paying its mana cost for as long as it remains exiled.` |  |
| Kianne, Corrupted Memory | Compound gap — `as long as <name>'s power is even, you may cast noncreature spells as though they had flash.`; `as long as <name>'s power is odd, you may cast creature spells as though they had flash.` |  |
| Overwhelming Stampede | `creatures you control gain trample and get +x/+x, where x is the greatest power among creatures you control until end of turn.` |  |
| Primordial Mist | `exile a face-down permanent you control face up: you may play that card this turn.` |  |
| Rashmi, Eternities Crafter | `whenever you cast your first spell each turn, reveal the top card of your library. you may cast it without paying its mana cost if it's a spell with lesser mana value. if you don't cast it, put it into your hand.` |  |
| Sandwurm Convergence | `creatures with flying can't attack you or planeswalkers you control.` |  |
| Scroll of Fate | `<cost>: manifest a card from your hand.` |  |
| Shigeki, Jukai Visionary | `<cost>, discard this card: return x target nonlegendary cards from your graveyard to your hand.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Shriekwood Devourer | `whenever you attack with <n> or more creatures, untap up to x lands, where x is the greatest power among those creatures.` |  |
| Thunderfoot Baloth | `as long as you control your commander, <name> gets +<n>/+<n> and other creatures you control get +<n>/+<n> and have trample.` |  |
| Whisperwood Elemental | `sacrifice <name>: until end of turn, face-up nontoken creatures you control gain <name>` |  |
| Yedora, Grave Gardener | `whenever another nontoken creature you control dies, you may return it to the battlefield face down under its owner's control. it's a forest land.` |  |


### Kodama (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Limit Break - Final Fantasy Commander (31 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Avalanche of Sector 7 | `whenever an opponent activates an ability of an artifact they control, <name> deals <n> damage to that player.` |  |
| Barret Wallace | `whenever <name> attacks, it deals damage equal to the number of equipped creatures you control to defending player.` |  |
| Barret, Avalanche Leader | `at the beginning of combat on your turn, attach up to <n> target equipment you control to target rebel you control.` |  |
| Cait Sith, Fortune Teller | `at the beginning of combat on your turn, scry <n>, then exile the top card of your library. you may play that card this turn. when you exile a card this way, target creature you control gets +x/+<n> until end of turn, where x is that card's mana value.` |  |
| Champion's Helm | `as long as equipped creature is legendary, it has hexproof.` |  |
| Cid, Freeflier Pilot | Compound gap — `<cost>, <cost>: return target equipment or vehicle card from your graveyard to your hand.`; `equipment and vehicle spells you cast cost <cost> less to cast.` |  |
| Clever Concealment | `any number of target nonland permanents you control phase out.` |  |
| Cloud's Limit Break | Compound gap — `• blade beam — <cost> — destroy any number of target tapped creatures with different controllers.`; `• cross-slash — <cost> — destroy target tapped creature.`; `• omnislash — <cost> — destroy all tapped creatures.` |  |
| Cloud, Ex-SOLDIER | `whenever <name> attacks, draw a card for each equipped attacking creature you control. then if <name> has power <n> or greater, create <n> treasure tokens.` |  |
| Elena, Turk Recruit | `when <name> enters, return target non-assassin historic card from your graveyard to your hand.` |  |
| Furious Rise | `at the beginning of your end step, if you control a creature with power <n> or greater, exile the top card of your library. you may play that card until you exile another card with <name>.` |  |
| Heidegger, Shinra Executive | `at the beginning of your end step, create a number of <n>/<n> white soldier creature tokens equal to the number of opponents who control more creatures than you.` |  |
| Hellkite Tyrant | Compound gap — `at the beginning of your upkeep, if you control twenty or more artifacts, you win the game.`; `whenever <name> deals combat damage to a player, gain control of all artifacts that player controls.` |  |
| Hero's Heirloom | `as long as equipped creature is legendary, it has trample and haste.` |  |
| Inspiring Statuary | `nonartifact spells you cast have improvise.` |  |
| Lifestream's Blessing | `draw x cards, where x is the greatest power among creatures you controlled as you cast this spell. if this spell was cast from exile, you gain twice x life.` |  |
| Mask of Memory | `whenever equipped creature deals combat damage to a player, you may draw <n> cards. if you do, discard a card.` |  |
| Professor Hojo | Compound gap — `the first activated ability you activate during your turn that targets a creature you control costs <cost> less to activate.`; `whenever <n> or more creatures you control become the target of an activated ability, draw a card. this ability triggers only once each turn.` |  |
| Puresteel Paladin | `equipment you control have equip <cost> as long as you control <n> or more artifacts.` |  |
| Red XIII, Proud Warrior | `when <name> enters, return target aura or equipment card from your graveyard to your hand.` |  |
| SOLDIER Military Program | Compound gap — `at the beginning of combat on your turn, choose <n>. if you control a commander, you may choose both instead.`; `• create a <n>/<n> white soldier creature token.`; `• put a +<n>/+<n> counter on each of up to <n> soldiers you control.` |  |
| Scavenger Grounds | `<cost>, <cost>, sacrifice a desert: exile all graveyards.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Sephiroth, Fallen Hero | `whenever <name> attacks, you may put a cell counter on target creature. until end of turn, each modified creature you control has base power and toughness <n>/<n>.` |  |
| Summon: Kujata | Compound gap — `i — lightning — <name> deals <n> damage to each of up to <n> target creatures.`; `ii — ice — up to <n> target creatures can't block this turn.`; `iii — fire — discard a card, then draw <n> cards. when you discard a card this way, <name> deals damage equal to that card's mana value to each opponent.` |  |
| Ultimate Magic: Holy | `permanents you control gain indestructible until end of turn. if this spell was cast from exile, prevent all damage that would be dealt to you this turn.` |  |
| Ultimate Magic: Meteor | `<name> deals <n> damage to each creature. if this spell was cast from exile, for each opponent, choose an artifact or land that player controls. destroy the chosen permanents.` |  |
| Unfinished Business | `return target creature card from your graveyard to the battlefield, then return up to <n> target aura and/or equipment cards from your graveyard to the battlefield attached to that creature.` |  |
| Vincent, Vengeful Atoner | `whenever <name> deals combat damage to an opponent, it deals that much damage to each other opponent if <name>'s power is <n> or greater.` |  |
| Wrecking Ball Arm | `equipped creature has base power and toughness <n>/<n> and can't be blocked by creatures with power <n> or less.` |  |
| Yuffie, Materia Hunter | `when <name> enters, gain control of target noncreature artifact for as long as you control <name>. then you may attach an equipment you control to <name>.` |  |
| Zack Fair | `<cost>, sacrifice <name>: target creature you control gains indestructible until end of turn. put <name>'s counters on that creature and attach an equipment that was attached to <name> to that creature.` |  |


### Living Energy - Aetherdrift Commander (18 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Academy Ruins | `<cost>, <cost>: put target artifact card from your graveyard on top of your library.` |  |
| Aetherflux Conduit | Compound gap — `<cost>, pay fifty <cost>: draw <n> cards. you may cast any number of spells from your hand without paying their mana costs.`; `whenever you cast a spell, you get an amount of <cost> equal to the amount of mana spent to cast that spell.` |  |
| Aetheric Amplifier | Compound gap — `<cost>, <cost>: choose <n>. activate only as a sorcery.`; `• double the number of each kind of counter on target permanent.`; `• double the number of each kind of counter you have.` |  |
| Aethertide Whale | `when <name> enters, you get <n> <cost>.` |  |
| Aetherworks Marvel | Compound gap — `<cost>, pay <n> <cost>: look at the top <n> cards of your library. you may cast a spell from among them without paying its mana cost. put the rest on the bottom of your library in a random order.`; `whenever a permanent you control is put into a graveyard, you get <cost>.` |  |
| Bespoke Battlewagon | `pay <cost>: <name> becomes an artifact creature until end of turn.` |  |
| Confiscation Coup | `choose target artifact or creature. you get <cost>, then you may pay an amount of <cost> equal to that permanent's mana value. if you do, gain control of it.` |  |
| Druid of Purification | `when <name> enters, starting with you, each player may choose an artifact or enchantment you don't control. destroy each permanent chosen this way.` | Also uncovered in: Commander Cube |
| Lightning Runner | `whenever <name> attacks, you get <cost>, then you may pay <n> <cost>. if you pay, untap all creatures you control, and after this phase, there is an additional combat phase.` |  |
| Midnight Clock | `when the twelfth hour counter is put on <name>, shuffle your hand and graveyard into your library, then draw <n> cards. exile <name>.` |  |
| Nissa, Worldsoul Speaker | `you may pay <n> <cost> rather than pay the mana cost for permanent spells you cast.` |  |
| Peema Aether-Seer | Compound gap — `pay <cost>: target creature blocks this turn if able.`; `when <name> enters, you get an amount of <cost> equal to the greatest power among creatures you control.` |  |
| Rampaging Aetherhood | `at the beginning of your upkeep, you get an amount of <cost> equal to <name>'s power. then you may pay <n> or more <cost>. if you do, put that many +<n>/+<n> counters on <name>.` |  |
| Saheeli, Radiant Creator | `at the beginning of combat on your turn, you may pay <cost>. when you do, create a token that's a copy of target permanent you control, except it's a <n>/<n> artifact creature in addition to its other types and has haste. sacrifice it at the beginning of the next end step.` |  |
| Saheeli, Sublime Artificer | `−<n>: target artifact you control becomes a copy of another target artifact or creature you control until end of turn, except it's an artifact in addition to its other types.` |  |
| Stridehangar Automaton | `if <n> or more artifact tokens would be created under your control, those tokens plus an additional <n>/<n> colorless thopter artifact creature token with flying are created instead.` |  |
| Territorial Aetherkite | `when <name> enters, you get <cost>. then you may pay <n> or more <cost>. when you do, <name> deals that much damage to each other creature.` |  |
| Triplicate Titan | `when <name> dies, create a <n>/<n> colorless golem artifact creature token with flying, a <n>/<n> colorless golem artifact creature token with vigilance, and a <n>/<n> colorless golem artifact creature token with trample.` |  |


### Mardu Surge - Tarkir: Dragonstorm Commander (17 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bone Devourer | `<name> enters with a number of +<n>/+<n> counters on it equal to the number of creatures that died this turn.` |  |
| Commander's Insignia | `creatures you control get +<n>/+<n> for each time you've cast your commander from the command zone this game.` |  |
| Divine Visitation | `if <n> or more creature tokens would be created under your control, that many <n>/<n> white angel creature tokens with flying and vigilance are created instead.` |  |
| Eliminate the Competition | `as an additional cost to cast this spell, sacrifice x creatures.` |  |
| Gix, Yawgmoth Praetor | Compound gap — `<cost>, discard x cards: exile the top x cards of target opponent's library. you may play lands and cast spells from among cards exiled this way without paying their mana costs.`; `whenever a creature deals combat damage to <n> of your opponents, its controller may pay <n> life. if they do, they draw a card.` |  |
| Grenzo, Havoc Raiser | Compound gap — `whenever a creature you control deals combat damage to a player, choose <n> —`; `• exile the top card of that player's library. until end of turn, you may cast that card and you may spend mana as though it were mana of any color to cast that spell.`; `• goad target creature that player controls.` |  |
| Infantry Shield | `equipped creature has menace and mobilize x, where x is its power.` |  |
| Kaya, Geist Hunter | Compound gap — `+<n>: creatures you control gain deathtouch until end of turn. put a +<n>/+<n> counter on up to <n> target creature token you control.`; `−<n>: exile all cards from all graveyards, then create a <n>/<n> white spirit creature token with flying for each card exiled this way.`; `−<n>: until end of turn, if <n> or more tokens would be created under your control, twice that many of those tokens are created instead.` |  |
| Legion Warboss | `at the beginning of combat on your turn, create a <n>/<n> red goblin creature token. that token gains haste until end of turn and attacks this combat if able.` |  |
| Mindblade Render | `whenever your opponents are dealt combat damage, if any of that damage was dealt by a warrior, you draw a card and you lose <n> life.` |  |
| Myr Battlesphere | `whenever <name> attacks, you may tap x untapped myr you control. if you do, <name> gets +x/+<n> until end of turn and deals x damage to the player or planeswalker it's attacking.` |  |
| Neriv, Crackling Vanguard | `whenever <name> attacks, exile a number of cards from the top of your library equal to the number of differently named tokens you control. during any turn you attacked with a commander, you may play those cards.` |  |
| Stroke of Midnight | `destroy target nonland permanent. its controller creates a <n>/<n> white human creature token.` | Also uncovered in: Commander Cube |
| Tempt with Vengeance | `create x <n>/<n> red elemental creature tokens with haste. each opponent may create x <n>/<n> red elemental creature tokens with haste. for each opponent who does, create x <n>/<n> red elemental creature tokens with haste.` |  |
| Thalisse, Reverent Medium | `at the beginning of each end step, create x <n>/<n> white spirit creature tokens with flying, where x is the number of tokens you created this turn.` |  |
| Windbrisk Heights | `<cost>, <cost>: you may play the exiled card without paying its mana cost if you attacked with <n> or more creatures this turn.` |  |
| Within Range | `whenever you attack, each opponent loses life equal to the number of creatures attacking them.` |  |


### Miracle Worker - Duskmourn: House of Horror Commander (20 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aminatou's Augury | `exile the top <n> cards of your library. you may put a land card from among them onto the battlefield. until end of turn, for each nonland card type, you may cast a spell of that type from among the exiled cards without paying its mana cost.` |  |
| Aminatou, Veil Piercer | `each enchantment card in your hand has miracle. its miracle cost is equal to its mana cost reduced by <cost>.` |  |
| Ancient Cellarspawn | Compound gap — `each spell you cast that's a demon, horror, or nightmare costs <cost> less to cast.`; `whenever you cast a spell, if the amount of mana spent to cast it was less than its mana value, target opponent loses life equal to the difference.` |  |
| Archetype of Imagination | `creatures your opponents control lose flying and can't have or gain flying.` |  |
| Arvinox, the Mind Flail | Compound gap — `<name> isn't a creature unless you control <n> or more permanents you don't own.`; `at the beginning of your end step, exile the bottom card of each opponent's library face down. for as long as those cards remain exiled, you may look at them, you may cast permanent spells from among them, and you may spend mana as though it were mana of any color to cast those spells.` |  |
| Bottomless Pool // Locker Room | `when you unlock this door, return up to <n> target creature to its owner's hand.` |  |
| Brainstone | `<cost>, <cost>, sacrifice <name>: draw <n> cards, then put <n> cards from your hand on top of your library in any order.` |  |
| Cramped Vents // Access Maze | `when you unlock this door, this room deals <n> damage to target creature an opponent controls. you gain life equal to the excess damage dealt this way.` |  |
| Demon of Fate's Design | Compound gap — `<cost>, sacrifice another enchantment: <name> gets +x/+<n> until end of turn, where x is the sacrificed enchantment's mana value.`; `once during each of your turns, you may cast an enchantment spell by paying life equal to its mana value rather than paying its mana cost.` |  |
| Dream Eater | `when <name> enters, surveil <n>. when you do, you may return target nonland permanent an opponent controls to its owner's hand.` |  |
| Fear of Sleep Paralysis | Compound gap — `stun counters can't be removed from permanents your opponents control.`; `whenever <name> or another enchantment you control enters and whenever you fully unlock a room, tap up to <n> target creature and put a stun counter on it.` |  |
| Hall of Heliod's Generosity | `<cost>, <cost>: put target enchantment card from your graveyard on top of your library.` |  |
| Nightmare Shepherd | `whenever another nontoken creature you control dies, you may exile it. if you do, create a token that's a copy of that creature, except it's <n>/<n> and it's a nightmare in addition to its other types.` |  |
| One with the Multiverse | `once during each of your turns, you may cast a spell from your hand or the top of your library without paying its mana cost.` |  |
| Phenomenon Investigators | Compound gap — `as <name> enters, choose believe or doubt.`; `• doubt — at the beginning of your end step, you may return a nonland permanent you own to your hand. if you do, draw a card.` |  |
| Secret Arcade // Dusty Parlor | `nonland permanents you control and permanent spells you control are enchantments in addition to their other types.` |  |
| Spirit-Sister's Call | `at the beginning of your end step, choose target permanent card in your graveyard. you may sacrifice a permanent that shares a card type with the chosen card. if you do, return the chosen card from your graveyard to the battlefield and it gains <name>` |  |
| Telling Time | `look at the top <n> cards of your library. put <n> of those cards into your hand, <n> on top of your library, and <n> on the bottom of your library.` |  |
| The Eldest Reborn | Compound gap — `i — each opponent sacrifices a creature or planeswalker of their choice.`; `iii — put target creature or planeswalker card from a graveyard onto the battlefield under your control.` |  |
| The Master of Keys | `each enchantment card in your graveyard has escape. the escape cost is equal to the card's mana cost plus exile <n> other cards from your graveyard.` |  |


### Oops! All Night's Whispers (6 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Breach the Multiverse | `each player mills <n> cards. for each player, choose a creature or planeswalker card in that player's graveyard. put those cards onto the battlefield under your control. then each creature you control becomes a phyrexian in addition to its other types.` |  |
| Fable of the Mirror-Breaker // Reflection of Kiki-Jiki | Compound gap — `i — create a <n>/<n> red goblin shaman creature token with <name>`; `ii — you may discard up to <n> cards. if you do, draw that many cards.` | Also uncovered in: Commander Cube |
| Palantír of Orthanc | `at the beginning of your end step, put an influence counter on <name> and scry <n>. then target opponent may have you draw a card. if that player doesn't, you mill x cards, where x is the number of influence counters on <name>, and that player loses life equal to the total mana value of those cards.` |  |
| Prismari, the Inspiration | `instant and sorcery spells you cast have storm.` |  |
| Ripples of Undeath | `at the beginning of your first main phase, mill <n> cards. then you may pay <cost> and <n> life. if you do, put a card from among those cards into your hand.` |  |
| Victimize | `choose <n> target creature cards in your graveyard. sacrifice a creature. if you do, return the chosen cards to the battlefield tapped.` | Also uncovered in: Riveteer Rampage - New Capenna Commander, Sultai Arisen - Tarkir: Dragonstorm Commander |


### Peace Offering - Bloomburrow Commander (17 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bloodroot Apothecary | Compound gap — `when <name> enters, you and target opponent each create a treasure token.`; `whenever an opponent sacrifices a noncreature token, that player gets <n> poison counters.` |  |
| Coiling Oracle | `when <name> enters, reveal the top card of your library. if it's a land card, put it onto the battlefield. otherwise, put that card into your hand.` |  |
| Communal Brewing | Compound gap — `when <name> enters, any number of target opponents each draw a card. put an ingredient counter on <name>, then put an ingredient counter on it for each card drawn this way.`; `whenever you cast a creature spell, that creature enters with x additional +<n>/+<n> counters on it, where x is the number of ingredient counters on <name>.` |  |
| Coveted Jewel | `whenever <n> or more creatures an opponent controls attack you and aren't blocked, that player draws <n> cards and gains control of <name>. untap it.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Fisher's Talent | Compound gap — `at the beginning of your upkeep, look at the top card of your library. you may reveal it if it's a land card. create a <n>/<n> blue fish creature token if you revealed it this way. then draw a card.`; `if you would create a fish token, create a <n>/<n> blue shark creature token instead.`; `if you would create a shark token, create an <n>/<n> blue octopus creature token instead.` |  |
| Illusionist's Gambit | Compound gap — `cast this spell only during the declare blockers step on an opponent's turn.`; `remove all attacking creatures from combat and untap them. after this phase, there is an additional combat phase. each of those creatures attacks that combat if able. they can't attack you or planeswalkers you control that combat.` |  |
| Intellectual Offering | Compound gap — `choose an opponent. untap all nonland permanents you control and all nonland permanents that player controls.`; `choose an opponent. you and that player each draw <n> cards.` |  |
| Jolrael, Mwonvuli Recluse | `<cost>: until end of turn, creatures you control have base power and toughness x/x, where x is the number of cards in your hand.` |  |
| Kwain, Itinerant Meddler | `<cost>: each player may draw a card, then each player who drew a card this way gains <n> life.` |  |
| Mr. Foxglove | `whenever <name> attacks, draw cards equal to the number of cards in defending player's hand minus the number of cards in your hand. if you didn't draw cards this way, you may put a creature card from your hand onto the battlefield.` |  |
| Octomancer | `at the beginning of each end step, create a token that's a copy of target creature token that entered the battlefield this turn.` |  |
| Selvala, Explorer Returned | `<cost>: each player reveals the top card of their library. for each nonland card revealed this way, add <cost> and you gain <n> life. then each player draws a card.` |  |
| Tempt with Bunnies | `draw a card and create a <n>/<n> white rabbit creature token. then each opponent may draw a card and create a <n>/<n> white rabbit creature token. for each opponent who does, you draw a card and you create a <n>/<n> white rabbit creature token.` |  |
| Tempt with Discovery | `search your library for a land card and put it onto the battlefield. each opponent may search their library for a land card and put it onto the battlefield. for each opponent who searches a library this way, search your library for a land card and put it onto the battlefield. then each player who searched a library this way shuffles.` |  |
| Tenuous Truce | Compound gap — `at the beginning of enchanted opponent's end step, you and that player each draw a card.`; `when you attack enchanted opponent or a planeswalker they control or when they attack you or a planeswalker you control, sacrifice <name>.` |  |
| Triskaidekaphile | `at the beginning of your upkeep, if you have exactly thirteen cards in your hand, you win the game.` |  |
| Twenty-Toed Toad | Compound gap — `whenever <name> attacks, you win the game if there are twenty or more counters on it or you have twenty or more cards in hand.`; `your maximum hand size is twenty.` |  |


### Raggadragga, Goreguts Boss (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Revival Trance - Final Fantasy Commander (23 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Archfiend of Depravity | `at the beginning of each opponent's end step, that player chooses up to <n> creatures they control, then sacrifices the rest.` |  |
| Banon, the Returners' Leader | Compound gap — `once during each of your turns, you may cast a creature spell from among cards in your graveyard that were put there from anywhere other than the battlefield this turn.`; `whenever you attack, you may pay <cost> and discard a card. if you do, draw a card.` |  |
| Coin of Fate | `<cost>, <cost>, exile <n> creature cards from your graveyard, sacrifice <name>: an opponent chooses <n> of the exiled cards. you put that card on the bottom of your library and return the other to the battlefield tapped. you become the monarch.` |  |
| Demolition Field | `<cost>, <cost>, sacrifice <name>: destroy target nonbasic land an opponent controls. that land's controller may search their library for a basic land card, put it onto the battlefield, then shuffle. you may search your library for a basic land card, put it onto the battlefield, then shuffle.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Espers to Magicite | `exile each opponent's graveyard. when you do, choose up to <n> target creature card exiled this way. create a token that's a copy of that card, except it's an artifact and it loses all other card types.` |  |
| Flayer of the Hatebound | `whenever <name> or another creature enters from your graveyard, that creature deals damage equal to its power to any target.` |  |
| Gogo, Mysterious Mime | `at the beginning of combat on your turn, you may have <name> become a copy of another target creature you control until end of turn, except its name is <name>. if you do, <name> and that creature each get +<n>/+<n> and gain haste until end of turn and attack this turn if able.` |  |
| Kefka, Dancing Mad | `at the beginning of your end step, exile a card at random from each opponent's graveyard. you may cast any number of spells from among cards exiled this way without paying their mana costs. then each player who owns a spell you cast this way loses life equal to its mana value.` |  |
| Legions to Ashes | `exile target nonland permanent an opponent controls and all tokens that player controls with the same name as that permanent.` |  |
| Locke, Treasure Hunter | `whenever <name> attacks, each player mills a card. if a land card was milled this way, create a treasure token. until end of turn, you may cast a spell from among those cards.` |  |
| Mog, Moogle Warrior | `at the beginning of your end step, each player may discard a card. each player who discarded a card this way draws a card. if a creature card was discarded this way, you create a <n>/<n> white moogle creature token with lifelink. then if a noncreature card was discarded this way, put a +<n>/+<n> counter on each moogle you control.` |  |
| Palace Jailer | `when <name> enters, exile target creature an opponent controls until an opponent becomes the monarch.` | Also uncovered in: Commander Cube |
| Phoenix Down | Compound gap — `<cost>, <cost>, exile <name>: choose <n> —`; `• exile target skeleton, spirit, or zombie.`; `• return target creature card with mana value <n> or less from your graveyard to the battlefield tapped.` |  |
| Rejoin the Fight | `mill <n> cards. then starting with the next opponent in turn order, each opponent chooses a creature card in your graveyard that hasn't been chosen. return each card chosen this way to the battlefield under your control.` |  |
| Rise of the Dark Realms | `put all creature cards from all graveyards onto the battlefield under your control.` |  |
| Sepulchral Primordial | `when <name> enters, for each opponent, you may put up to <n> target creature card from that player's graveyard onto the battlefield under your control.` |  |
| Setzer, Wandering Gambler | Compound gap — `when <name> enters, create the blackjack, a legendary <n>/<n> colorless vehicle artifact token with flying and crew <n>.`; `whenever a vehicle you control deals combat damage to a player, flip a coin.`; `whenever you win a coin flip, create <n> tapped treasure tokens.` |  |
| Shadow, Mysterious Assassin | `throw — whenever <name> deals combat damage to a player, you may sacrifice another nonland permanent. if you do, draw <n> cards and each opponent loses life equal to the mana value of the sacrificed permanent.` |  |
| Siegfried, Famed Swordsman | `when <name> enters, mill <n> cards. then put x +<n>/+<n> counters on <name>, where x is twice the number of creature cards in your graveyard.` |  |
| Snort | `each player may discard their hand and draw <n> cards. then <name> deals <n> damage to each opponent who discarded their hand this way.` |  |
| Strago and Relm | `<cost>, <cost>: target opponent exiles cards from the top of their library until they exile an instant, sorcery, or creature card. you may cast that card without paying its mana cost. if you cast a creature spell this way, it gains haste and <name> activate only as a sorcery.` |  |
| Summon: Esper Valigarmanda | Compound gap — `i — exile an instant or sorcery card from each graveyard.`; `ii, iii, iv — add <cost> for each lore counter on this saga. you may cast an instant or sorcery card exiled with this saga, and mana of any type can be spent to cast that spell.` |  |
| The Warring Triad | `<cost>, mill a card: target player adds <n> mana of any color.` |  |


### Riveteer Rampage - New Capenna Commander (13 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bellowing Mauler | `at the beginning of your end step, each player loses <n> life unless they sacrifice a nontoken creature of their choice.` |  |
| Deathbringer Regent | `when <name> enters, if you cast it from your hand and there are <n> or more other creatures on the battlefield, destroy all other creatures.` |  |
| First Responder | `at the beginning of your end step, you may return another creature you control to its owner's hand, then put a number of +<n>/+<n> counters equal to that creature's power on <name>.` |  |
| Grime Gorger | `whenever <name> attacks, exile up to <n> card of each card type from defending player's graveyard. put a +<n>/+<n> counter on <name> for each card exiled this way.` |  |
| Henzie "Toolbox" Torre | `each creature spell you cast with mana value <n> or greater has blitz. the blitz cost is equal to its mana cost.` |  |
| Industrial Advancement | `at the beginning of your end step, you may sacrifice a creature. if you do, look at the top x cards of your library, where x is that creature's mana value. you may put a creature card from among them onto the battlefield. put the rest on the bottom of your library in a random order.` |  |
| Mezzio Mugger | `whenever <name> attacks, exile the top card of each player's library. you may play those cards this turn, and you may spend mana as though it were mana of any color to cast those spells.` |  |
| Mitotic Slime | `when <name> dies, create <n> <n>/<n> green ooze creature tokens. they have <name>` |  |
| Next of Kin | `when enchanted creature dies, you may put a creature card you own with lesser mana value from your hand or from the command zone onto the battlefield. if you do, return this card to the battlefield attached to that creature at the beginning of the next end step.` |  |
| Protection Racket | `at the beginning of your upkeep, repeat the following process for each opponent in turn order. reveal the top card of your library. that player may pay life equal to that card's mana value. if they do, exile that card. otherwise, put it into your hand.` |  |
| The Beamtown Bullies | `<cost>: target opponent whose turn it is puts target nonlegendary creature card from your graveyard onto the battlefield under their control. it gains haste. goad it. at the beginning of the next end step, exile it.` |  |
| Turf War | `whenever a creature deals combat damage to a player, if that player controls <n> or more lands with contested counters on them, that creature's controller gains control of <n> of those lands of their choice and untaps it.` |  |
| Wave of Rats | `when <name> dies, if it dealt combat damage to a player this turn, return it to the battlefield under its owner's control.` |  |


### Scions & Spellcraft - Final Fantasy Commander (18 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Ardbert, Warrior of Darkness | Compound gap — `whenever you cast a black spell, put a +<n>/+<n> counter on each legendary creature you control. they gain menace until end of turn.`; `whenever you cast a white spell, put a +<n>/+<n> counter on each legendary creature you control. they gain vigilance until end of turn.` |  |
| Blue Mage's Cane | `equipped creature gets +<n>/+<n>, is a wizard in addition to its other types, and has <name>` |  |
| Champions from Beyond | `whenever you attack with <n> or more creatures, those creatures get +<n>/+<n> until end of turn.` |  |
| Circle of Power | `you draw <n> cards and you lose <n> life. create a <n>/<n> black wizard creature token with <name>` |  |
| Dancer's Chakrams | `equipped creature gets +<n>/+<n>, has lifelink and <name> and is a performer in addition to its other types.` |  |
| Estinien Varlineau | `at the beginning of your second main phase, you draw x cards and lose x life, where x is the number of your opponents who were dealt combat damage by <name> or a dragon this turn.` |  |
| Eye of Nidhogg | `enchanted creature is a black dragon with base power and toughness <n>/<n>, has flying and deathtouch, and is goaded.` |  |
| G'raha Tia, Scion Reborn | `whenever you cast a noncreature spell, you may pay x life, where x is that spell's mana value. if you do, create a <n>/<n> colorless hero creature token and put x +<n>/+<n> counters on it. do this only once each turn.` |  |
| Krile Baldesion | `whenever you cast a noncreature spell, you may return target creature card with mana value equal to that spell's mana value from your graveyard to your hand. do this only once each turn.` |  |
| Lethal Scheme | `destroy target creature or planeswalker. each creature that convoked this spell connives.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Observed Stasis | Compound gap — `enchanted creature loses all abilities and can't attack or block.`; `when <name> enters, remove enchanted creature from combat. then draw a card for each tapped creature its controller controls.` |  |
| Papalymo Totolymo | `<cost>, <cost>, sacrifice <name>: each opponent who lost life this turn sacrifices a creature with the greatest power among creatures they control.` |  |
| Reaper's Scythe | Compound gap — `at the beginning of your end step, put a soul counter on <name> for each player who lost life this turn.`; `equipped creature gets +<n>/+<n> for each soul counter on <name> and is an assassin in addition to its other types.` |  |
| Summon: Good King Mog XII | `ii, iii — whenever you cast a noncreature spell this turn, create a token that's a copy of a non-saga token you control.` |  |
| Thancred Waters | `when <name> enters, another target legendary permanent you control gains indestructible for as long as you control <name>.` |  |
| Torrential Gearhulk | `when <name> enters, you may cast target instant card from your graveyard without paying its mana cost. if that spell would be put into your graveyard, exile it instead.` |  |
| Transpose | `draw a card, then discard a card. you lose <n> life. if this spell was cast from your hand, create a <n>/<n> black wizard creature token with <name>` |  |
| Urianger Augurelt | Compound gap — `<cost>: look at the top card of your library. you may exile it face down.`; `<cost>: until end of turn, you may play cards exiled with <name>. spells you cast this way cost <cost> less to cast.`; `whenever you play a land from exile or cast a spell from exile, you gain <n> life.` |  |


### Shorikai Vehicles (20 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aerial Surveyor | `whenever <name> attacks, if defending player controls more lands than you, search your library for a basic plains card, put it onto the battlefield tapped, then shuffle.` |  |
| Born to Drive | `<cost>, discard this card: create <n> <n>/<n> colorless pilot creature tokens with <name>` |  |
| Dermotaxi | Compound gap — `as <name> enters, exile a creature card from a graveyard.`; `tap <n> untapped creatures you control: until end of turn, <name> becomes a copy of the exiled card, except it's a vehicle artifact in addition to its other types.` |  |
| Digsite Engineer | `whenever you cast an artifact spell, you may pay <cost>. if you do, create a <n>/<n> colorless construct artifact creature token with <name>` | Also uncovered in: Commander Cube |
| Mech Hangar | `<cost>, <cost>: target vehicle becomes an artifact creature until end of turn.` |  |
| Mechtitan Core | `<cost>, exile <name> and <n> other artifact creatures and/or vehicles you control: create mechtitan, a legendary <n>/<n> construct artifact creature token with flying, vigilance, trample, lifelink, and haste that's all colors. when that token leaves the battlefield, return all cards exiled with <name> except this card to the battlefield tapped under their owners' control.` |  |
| Mobile Garrison | `whenever <name> attacks, untap another target artifact or creature you control.` |  |
| Mobilizer Mech | `whenever <name> becomes crewed, up to <n> other target vehicle you control becomes an artifact creature until end of turn.` |  |
| Mutavault | `<cost>: <name> becomes a <n>/<n> creature with all creature types until end of turn. it's still a land.` |  |
| Padeem, Consul of Innovation | `at the beginning of your upkeep, if you control the artifact with the greatest mana value or tied for the greatest mana value, draw a card.` |  |
| Peacewalker Colossus | `<cost>: another target vehicle you control becomes an artifact creature until end of turn.` |  |
| Prodigy's Prototype | `whenever <n> or more vehicles you control attack, create a <n>/<n> colorless pilot creature token with <name>` |  |
| Rebbec, Architect of Ascension | `artifacts you control have protection from each mana value among artifacts you control.` |  |
| Reckoner Bankbuster | `<cost>, <cost>, remove a charge counter from <name>: draw a card. then if there are no charge counters on <name>, create a treasure token and a <n>/<n> colorless pilot creature token with <name>` |  |
| Shorikai, Genesis Engine | `<cost>, <cost>: draw <n> cards, then discard a card. create a <n>/<n> colorless pilot creature token with <name>` |  |
| Smuggler's Copter | `whenever <name> attacks or blocks, you may draw a card. if you do, discard a card.` | Also uncovered in: Commander Cube |
| Surgehacker Mech | `when <name> enters, it deals damage equal to twice the number of vehicles you control to target creature or planeswalker an opponent controls.` |  |
| The Millennium Calendar | Compound gap — `when there are <n>,<n> or more time counters on <name>, sacrifice it and each opponent loses <n>,<n> life.`; `whenever you untap <n> or more permanents during your untap step, put that many time counters on <name>.` |  |
| The Wanderer | `prevent all noncombat damage that would be dealt to you and other permanents you control.` |  |
| Unwinding Clock | `untap all artifacts you control during each other player's untap step.` |  |


### SpongeBob and the legendary Burger (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### Sultai Arisen - Tarkir: Dragonstorm Commander (13 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Afterlife from the Loam | `for each player, choose up to <n> target creature card in that player's graveyard. put those cards onto the battlefield under your control. they're zombies in addition to their other types.` |  |
| Amphin Mutineer | `when <name> enters, exile up to <n> target non-salamander creature. that creature's controller creates a <n>/<n> blue salamander warrior creature token.` | Also uncovered in: Commander Cube |
| Consuming Aberration | `whenever you cast a spell, each opponent reveals cards from the top of their library until they reveal a land card, then puts those cards into their graveyard.` |  |
| Diviner of Mist | `whenever <name> attacks, mill <n> cards. you may cast an instant or sorcery spell from your graveyard with mana value <n> or less without paying its mana cost. if that spell would be put into your graveyard, exile it instead.` |  |
| Jarad, Golgari Lich Lord | `sacrifice a swamp and a forest: return this card from your graveyard to your hand.` |  |
| Kishla Skimmer | `whenever a card leaves your graveyard during your turn, draw a card. this ability triggers only once each turn.` |  |
| Kotis, Sibsig Champion | Compound gap — `once during each of your turns, you may cast a creature spell from your graveyard by exiling <n> other cards from your graveyard in addition to paying its other costs.`; `whenever <n> or more creatures you control enter, if <n> or more of them entered from a graveyard or was cast from a graveyard, put <n> +<n>/+<n> counters on <name>.` |  |
| Meren of Clan Nel Toth | Compound gap — `at the beginning of your end step, choose target creature card in your graveyard. if that card's mana value is less than or equal to the number of experience counters you have, return it to the battlefield. otherwise, put it into your hand.`; `whenever another creature you control dies, you get an experience counter.` |  |
| Necromantic Selection | `destroy all creatures, then return a creature card put into a graveyard this way to the battlefield under your control. it's a black zombie in addition to its other colors and types. exile <name>.` |  |
| Ob Nixilis, the Fallen | `whenever a land you control enters, you may have target player lose <n> life. if you do, put <n> +<n>/+<n> counters on <name>.` |  |
| Steward of the Harvest | Compound gap — `creatures you control have all activated abilities of all land cards exiled with <name>.`; `when <name> enters, exile up to <n> target land cards from your graveyard.` |  |
| Tasigur, the Golden Fang | `<cost>: mill <n> cards, then return a nonland card of an opponent's choice from your graveyard to your hand.` |  |
| Welcome the Dead | `draw <n> cards, then discard a card and you lose <n> life. create x tapped <n>/<n> black zombie druid creature tokens, where x is the number of cards that were put into your graveyard from your hand or library this turn.` |  |


### Temur Roar - Tarkir: Dragonstorm Commander (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Breaching Dragonstorm | `when <name> enters, exile cards from the top of your library until you exile a nonland card. you may cast it without paying its mana cost if that spell's mana value is <n> or less. if you don't, put that card into your hand.` |  |
| Broodcaller Scourge | `whenever <n> or more dragons you control deal combat damage to a player, you may put a permanent card with mana value less than or equal to that damage from your hand onto the battlefield.` | Also uncovered in: Commander Cube |
| Deceptive Frostkite | `you may have <name> enter as a copy of a creature you control with power <n> or greater, except it's a dragon in addition to its other types and it has flying.` |  |
| Eshki, Temur's Roar | `whenever you cast a creature spell, put a +<n>/+<n> counter on <name>. if that spell's power is <n> or greater, draw a card. if that spell's power is <n> or greater, <name> deals damage equal to <name>'s power to each opponent.` |  |
| Gadrak, the Crown-Scourge | `at the beginning of your end step, create a treasure token for each nontoken creature that died this turn.` |  |
| Hammerhead Tyrant | `whenever you cast a spell, return up to <n> target nonland permanent an opponent controls with mana value less than or equal to that spell's mana value to its owner's hand.` |  |
| Haven of the Spirit Dragon | `<cost>, <cost>, sacrifice <name>: return target dragon creature card or ugin planeswalker card from your graveyard to your hand.` |  |
| Hellkite Courser | `when <name> enters, you may put a commander you own from the command zone onto the battlefield. it gains haste. return it to the command zone at the beginning of the next end step.` |  |
| Nesting Dragon | `whenever a land you control enters, create a <n>/<n> red dragon egg creature token with defender and <name>` |  |
| Nogi, Draco-Zealot | `whenever <name> attacks, if you control <n> or more dragons, until end of turn, <name> becomes a dragon with base power and toughness <n>/<n> and gains flying.` |  |
| Opportunistic Dragon | `when <name> enters, choose target human or artifact an opponent controls. for as long as <name> remains on the battlefield, gain control of that permanent, it loses all abilities, and it can't attack or block.` |  |
| Parapet Thrasher | Compound gap — `whenever <n> or more dragons you control deal combat damage to an opponent, choose <n> that hasn't been chosen this turn —`; `• <name> deals <n> damage to each other opponent.`; `• destroy target artifact that opponent controls.`; `• exile the top card of your library. you may play it this turn.` | Also uncovered in: Commander Cube |
| Reflections of Littjara | `whenever you cast a spell of the chosen type, copy that spell.` |  |
| Sarkhan, Soul Aflame | `whenever a dragon you control enters, you may have <name> become a copy of it until end of turn, except its name is <name> and it's legendary in addition to its other types.` |  |
| Scourge of the Throne | `whenever <name> attacks for the first time each turn, if it's attacking the player with the most life or tied for most life, untap all attacking creatures. after this phase, there is an additional combat phase.` |  |
| Selvala's Stampede | `starting with you, each player votes for wild or free. reveal cards from the top of your library until you reveal a creature card for each wild vote. put those creature cards onto the battlefield, then shuffle the rest into your library. you may put a permanent card from your hand onto the battlefield for each free vote.` |  |
| Steel Hellkite | `<cost>: destroy each nonland permanent with mana value x whose controller was dealt combat damage by <name> this turn. activate only once each turn.` |  |
| Stormbreath Dragon | `when <name> becomes monstrous, it deals damage to each opponent equal to the number of cards in that player's hand.` |  |
| Temple of the Dragon Queen | `as <name> enters, you may reveal a dragon card from your hand. <name> enters tapped unless you revealed a dragon card this way or you control a dragon.` |  |
| Territorial Hellkite | `at the beginning of combat on your turn, choose an opponent at random that <name> didn't attack during your last combat. <name> attacks that player this combat if able. if you can't choose an opponent this way, tap <name>.` |  |
| Thundermane Dragon | `you may cast creature spells with power <n> or greater from the top of your library. if you cast a creature spell this way, it gains haste until end of turn.` |  |
| Whirlwing Stormbrood // Dynamic Soar | `you may cast sorcery spells and dragon spells as though they had flash.` |  |


### Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| April O'Neil, Live on the Scene | `whenever a mutant, ninja, or turtle you control enters, investigate.` |  |
| Bebop, Skull & Crossbones | `whenever <name> deals combat damage to a player, you may draw x cards, where x is the number of counters on <name>. if you do, you lose x life.` |  |
| Big Mother Mouser | `when <name> dies, create a number of <n>/<n> colorless robot artifact creature tokens equal to the number of +<n>/+<n> counters on <name>.` |  |
| Casey Jones, Back Alley Brute | `whenever you put <n> or more +<n>/+<n> counters on a creature you control, <name> deals that much damage to target opponent.` |  |
| Coin of Mastery | `each creature you control enters with an additional +<n>/+<n> counter on it for each mana from an artifact source spent to cast it.` |  |
| Continue? | `choose up to <n> target creature cards in your graveyard that were put there from the battlefield this turn. return them to the battlefield.` |  |
| Dimension X Pizzasaur | `when <name> enters, put <n> +<n>/+<n> counters on target creature. when you do, destroy up to <n> target creature with mana value less than or equal to the number of counters among permanents you control.` |  |
| Double Jump // Flying Kick | `put a flying counter on target creature you control. until end of turn, it has base power and toughness <n>/<n>.` |  |
| Everything Pizza | `<cost>, <cost>, sacrifice <name>: target player gains <n> life and draws a card. each of your opponents discards a card. <name> deals <n> damage to any target. put <n> +<n>/+<n> counters on up to <n> target creature.` |  |
| Fast Forward | `this spell costs <cost> less to cast for each opponent you attacked this turn.` |  |
| Foot Chopper | `whenever equipped creature deals combat damage to a player, you may sacrifice it. if you do, draw cards equal to its power.` |  |
| Game Over | `this spell costs <cost> less to cast if a player's life total is less than or equal to half their starting life total.` |  |
| Here Comes a New Hero! | `target player draws x cards. create a token that's a copy of up to <n> target creature with mana value x or less.` |  |
| Heroes in a Half Shell | `whenever <n> or more mutants, ninjas, and/or turtles you control deal combat damage to a player, put a +<n>/+<n> counter on each of those creatures and draw a card.` |  |
| Hidden Hideout | `<cost>, <cost>: target creature you control with a counter on it gains lifelink until end of turn.` |  |
| High Score | `at the beginning of your end step, draw a card if you control a creature with the greatest power among creatures on the battlefield.` |  |
| Irma, Part-Time Mutant | `at the beginning of combat on your turn, <name> becomes a copy of up to <n> other target creature you control, except her name is <name> and she has this ability. then put a +<n>/+<n> counter on her.` |  |
| Michelangelo, the Heart | `raid — at the beginning of your second main phase, if you attacked this turn, put a +<n>/+<n> counter on target creature and create a food token.` |  |
| Mole Module | `whenever <name> deals combat damage to a player, mill <n> cards. you may put a permanent card from among them onto the battlefield.` |  |
| Ninja Pizza | `foods you control have <name>` |  |
| Shellshock | `for each opponent, choose up to <n> target creature that player controls. <name> deals x damage to each of those creatures. you create a mutagen token for each creature dealt damage this way.` |  |
| Swift Demise | `<name> deals <n> damage to target creature. then destroy each creature you don't control that was dealt damage this turn.` |  |


### Wick Snail Boom (0 cards)

| Card | Gap | Notes |
| --- | --- | --- |


### World Shaper - Edge of Eternities Commander Deck (3 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Eumidian Wastewaker | `whenever <name> attacks, you and defending player each discard a card or sacrifice a permanent. you draw a card for each land card put into a graveyard this way.` |  |
| Evendo Brushrazer | Compound gap — `during your turn, as long as you've sacrificed a nontoken permanent this turn, you may play cards exiled with <name>.`; `whenever you sacrifice a nontoken permanent, exile the top card of your library.` |  |
| Exploration Broodship | `once during each of your turns, you may cast a permanent spell from your graveyard by sacrificing a land in addition to paying its other costs.` |  |


### yshtola (0 cards)

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
| Conformer Shuriken | Granted "Whenever ~ attacks, tap target creature defending player controls. If that creature has greater power than ~, put a number of +1/+1 counters on ~ equal to the difference." | The counters go on the *Equipment*, and the count is a power difference against a just-tapped target — no composition reads that. |
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
| Vincent, Vengeful Atoner | `Whenever ~ deals combat damage to an opponent, it deals that much damage to each other opponent if ~'s power is 7 or greater.` | An intervening-if on the source's own power. |
