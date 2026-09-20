# Singleton queue

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
| Dreadlight Monstrosity | "Activate only if you own a card in exile" | An ownership-scoped (not controller-scoped) exile-zone activation condition. |
| Secret Tunnel | "2 target creatures you control that share a creature type" | A same-type-as-each-other multi-target filter (cross-target constraint, not a fixed filter). |
| Open into Wonder | X target creatures, then a quoted-grant tail on "those creatures" | X-count multi-target combined with a group quoted-ability grant. |
| Trygon Prime | "Put a counter on it AND on target `<X>`" — two objects countered by one trigger | A dual-counter body (self + a separate target), not the single-counter shape every existing handler expects. |
| Unquenchable Fury | "Each minotaur can't be blocked this turn except by 2 or more creatures" | Mass/subtype-scoped unblockable with a *count*-based (not filter-based) except-by clause; `UnblockableEffect.selector` is a closed name enum, not filterable. |
| Chromium, the Mutable | "Becomes a human with base P/T 1/1, loses all abilities, and gains hexproof" | `_BASE_PT`-shaped, not `_ANIMATE_SELF`-shaped — a "loses all abilities" clause combined with a base-P/T set and a keyword grant in one sentence. |
| Writ of Passage | "Whenever enchanted creature attacks, if its power is 2 or less, `<effect>`" | An intervening-if reading the *attacker's own* power — the existing `attacked_player_has_most/lowest_life`-style gates all read the defender's state, a different subject. |
| Evie Frye | Loot (draw then discard), with a sub-trigger conditioned on the discarded card's type | The "when you discard a `<type>` card this way" sub-trigger inside a loot ability. |
| Mistford River Turtle | "Another target attacking **non-human** creature" | A subtype-*negation* qualifier on an attacking-creature target; no other cached card pairs "non-`<type>`" with this target shape. |
| Shrouded Serpent | "Defending player may pay `{4}`. If that player doesn't, `<effect>`" | A combat-trigger tax-or-else composition, distinct from the shipped attack-tax statics (this one gates a *different* effect on non-payment, not the attack itself). |
| Temmet, Vizier of Naktamun | "Target creature **token** you control" combined with pump + unblockable in one trigger | The "token" qualifier on this exact combined effect body; the one other cached card sharing "target creature token you control" (Kaya, Geist Hunter) is blocked on unrelated clauses too, so no real shared yield today. |
| First Responder | Untargeted "return another creature you control to hand, **then** put counters on ~ equal to that creature's power" | Related to PAR-98's targeted-return-then-measure bucket but a third, distinct shape: "then" (not "if you do") sequencing, and a magnitude reading the just-returned creature's *power* rather than gating on success. |
| Indoctrination Attendant | "If you do, create a 1/1 … token with toxic 1 **and** '`<quoted static ability>`'" | A printed-keyword-count-plus-quoted-ability token-creation compound; no token-creation handler combines both yet. |
| Goblin Ski Patrol | "Activate only once **and only if** you control a snow Mountain." — reversed "only once and only if" order (`_ACTIVATE_ONLY_IF_TRAILING_RE` only recognizes "only if `<cond>` [and only once]"), plus a "snow `<land type>`" control-count selector `_CONTROL_COUNT_SELECTORS` doesn't have | PAR-117's sacrifice-verb closure (PARSER_VERSION 417) unblocked the card's own sacrifice clause; this trailing activation-condition is the sole remaining gap, confirmed 1 SOLO/0 also-blocked via `parser_probe.py blocked "activate only once and only if"`. |
| Adverse Conditions | Its inline Eldrazi Scion token's quoted "Sacrifice this token: Add {C}" activated mana ability | PAR-84 now recognizes the preceding multi-target tap/next-untap sequence. The remaining full body is 1 SOLO/0 also-blocked (`parser_probe.py blocked "tap up to [0-9]+ target creatures\\. those creatures don.t untap"`); `CreateTokenEffect` has no generic inline-token activated-ability field, so this is a token-definition singleton, not a tap/untap parser family. |

See `docs/implementation-state/BACKLOG.md`'s PAR-98 entry for the related
*clustered* residue these were sorted out of (2+ cards sharing one gap —
those are tickets, not singletons).

## Batch 2 — 2026-09-16 saved-deck coverage sweep

The rows below were **not** individually re-diagnosed with `parser_probe.py blocked` the way the queue above was — at this volume (1,020 cards across all 56 saved decks) that is a multi-session undertaking, tracked as an explicit follow-up rather than rushed. Instead every row passed a **mechanically equivalent, cache-wide check**: one `parse_oracle` pass over the full card cache (same `abstract_clause` normalization `commander_tail_report.py` uses) confirmed each card's unclaimed clause(s) have **no sibling anywhere in the cache** — a card with exactly one unclaimed clause unique cache-wide is listed plain; a card whose several unclaimed clauses are *each* individually unique is listed as a **compound gap** (all of them, not just one, would need a handler). A card with *any* clause that DOES cluster with another card was routed to a `PAR-*` ticket instead (PAR-99...PAR-114) or left for a future ticket batch — never listed here. Re-run the check before hand-authoring: a later batch can turn one of these into a two-card cluster, at which point promote it out per this file's own standing rule. Grouped by the saved deck each card was found uncovered in (its first non-cube deck, if it appears in more than one); `Commander Cube`/`cEDH staples`/`cEDH staples 2` cards with no non-cube deck are grouped under the cube itself. PARSER_VERSION 413.


### Abzan Armor - Tarkir: Dragonstorm Commander (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Assault Formation | `<cost>: target creature with defender can attack this turn as though it didn't have defender.` |  |
| Baldin, Century Herdmaster | `Whenever ~ attacks, up to <n> hundred target creatures each get +<n>/+x until end of turn, where x is the number of cards in your hand.` |  |
| Betor, Ancestor's Voice | `At the beginning of your end step, put a number of +<n>/+<n> counters on up to <n> other target creature you control equal to the amount of life you gained this turn. return up to <n> target creature card with mana value less than or equal to the amount of life you lost this turn from your graveyard to the battlefield.` | Also uncovered in: Commander Cube |
| Blight Pile | `<cost>, <cost>: each opponent loses x life, where x is the number of creatures with defender you control.` |  |
| Canopy Gargantuan | `At the beginning of your upkeep, put a number of +<n>/+<n> counters on each other creature you control equal to that creature's toughness.` |  |
| Colfenor's Urn | Compound gap — `At the beginning of the end step, if <n> or more cards have been exiled with ~, sacrifice it. if you do, return those cards to the battlefield under their owner's control.`; `Whenever a creature with toughness <n> or greater is put into your graveyard from the battlefield, you may exile it.` |  |
| Expel the Interlopers | `Choose a number between <n> and <n>. destroy all creatures with power greater than or equal to the chosen number.` |  |
| Jaws of Defeat | `Whenever a creature you control enters, target opponent loses life equal to the difference between that creature's power and its toughness.` |  |
| Rampart Architect | `Whenever a creature you control with defender dies, you may search your library for a basic land card, put that card onto the battlefield tapped, then shuffle.` |  |
| Reunion of the House | `Return any number of target creature cards with total power <n> or less from your graveyard to the battlefield. exile ~.` |  |
| Shalai, Voice of Plenty | `You, planeswalkers you control, and other creatures you control have hexproof.` | Also uncovered in: SpongeBob and the legendary Burger |
| Sidar Kondo of Jamuraa | `Creatures your opponents control without flying or reach can't block creatures with power <n> or less.` |  |
| Staff of Compleation | `<cost>, pay <n> life: destroy target permanent you own.` |  |
| Tip the Scales | `Sacrifice a creature. when you do, all creatures get -x/-x until end of turn, where x is the sacrificed creature's toughness.` |  |
| Towering Titan | `~ enters with x +<n>/+<n> counters on it, where x is the total toughness of other creatures you control.` |  |
| Tree of Redemption | `<cost>: exchange your life total with ~'s toughness.` |  |
| Wakestone Gargoyle | `<cost>: creatures you control with defender can attack this turn as though they didn't have defender.` |  |
| Walking Bulwark | `<cost>: until end of turn, target creature with defender gains haste, can attack as though it didn't have defender, and assigns combat damage equal to its toughness rather than its power. activate only as a sorcery.` |  |
| Wall of Limbs | `<cost>, sacrifice ~: target player loses x life, where x is ~'s power.` |  |
| Wall of Reverence | `At the beginning of your end step, you may gain life equal to the power of target creature you control.` | Also uncovered in: Hope to the last |
| Weathered Sentinels | `~ can attack players who attacked you during their last turn as though it didn't have defender.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Wingmantle Chaplain | Compound gap — `When ~ enters, create a <n>/<n> white bird creature token with flying for each creature with defender you control.`; `Whenever another creature you control with defender enters, create a <n>/<n> white bird creature token with flying.` |  |


### Animated Army - Bloomburrow Commander (23 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Alchemist's Talent | Compound gap — `Treasures you control have ~`; `Whenever you cast a spell, if mana from a treasure was spent to cast it, this class deals damage equal to that spell's mana value to each opponent.` |  |
| Bello, Bard of the Brambles | `During your turn, each non-equipment artifact and non-aura enchantment you control with mana value <n> or greater is a <n>/<n> elemental creature in addition to its other types and has indestructible, haste, and ~` |  |
| Brightcap Badger // Fungus Frolic | `Each fungus and saproling you control has ~` | Also uncovered in: Commander Cube |
| Decimate | `Destroy target artifact, target creature, target enchantment, and target land.` | Also uncovered in: Limit Break - Final Fantasy Commander |
| Esika's Chariot | `Whenever ~ attacks, create a token that's a copy of target token you control.` |  |
| Evercoat Ursine | `Whenever ~ deals combat damage to a player, if there are cards exiled with it, you may play <n> of them without paying its mana cost.` |  |
| Garruk's Packleader | `Whenever another creature you control with power <n> or greater enters, you may draw a card.` |  |
| Ghalta, Primal Hunger | `This spell costs <cost> less to cast, where x is the total power of creatures you control.` | Also uncovered in: Raggadragga, Goreguts Boss |
| Goreclaw, Terror of Qal Sisma | Compound gap — `Creature spells you cast with power <n> or greater cost <cost> less to cast.`; `Whenever ~ attacks, each creature you control with power <n> or greater gets +<n>/+<n> and gains trample until end of turn.` | Also uncovered in: Commander Cube |
| Greater Good | `Sacrifice a creature: draw cards equal to the sacrificed creature's power, then discard <n> cards.` | Also uncovered in: Hydranten |
| Grothama, All-Devouring | Compound gap — `Other creatures have ~`; `When ~ leaves the battlefield, each player draws cards equal to the amount of damage dealt to ~ this turn by sources they controlled.` |  |
| Grumgully, the Generous | `Each other non-human creature you control enters with an additional +<n>/+<n> counter on it.` |  |
| Mosswort Bridge | `<cost>, <cost>: you may play the exiled card without paying its mana cost if creatures you control have total power <n> or greater.` | Also uncovered in: Jump Scare! - Duskmourn: House of Horror Commander, Riveteer Rampage - New Capenna Commander, Temur Roar - Tarkir: Dragonstorm Commander |
| Path of Discovery | `Whenever a creature you control enters, it explores.` | Also uncovered in: Counter Blitz - Final Fantasy Commander |
| Prosperous Bandit | `Whenever ~ deals combat damage to a player, create that many tapped treasure tokens.` |  |
| Rain of Riches | `The first spell you cast each turn that mana from a treasure was spent to cast has cascade.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Rolling Hamsphere | Compound gap — `~ gets +<n>/+<n> for each hamster you control.`; `Whenever ~ attacks, create <n> <n>/<n> red hamster creature tokens, then it deals x damage to any target, where x is the number of hamsters you control.` |  |
| Teapot Slinger | `Whenever you expend <n>, ~ deals <n> damage to each opponent.` |  |
| Thickest in the Thicket | Compound gap — `At the beginning of your end step, draw <n> cards if you control the creature with the greatest power or tied for the greatest power.`; `When ~ enters, put x +<n>/+<n> counters on target creature, where x is that creature's power.` |  |
| Trailtracker Scout | `Whenever you expend <n>, return up to <n> target permanent card from your graveyard to your hand.` |  |
| Wandertale Mentor | `Whenever you expend <n>, put a +<n>/+<n> counter on ~.` |  |
| Warstorm Surge | `Whenever a creature you control enters, it deals damage equal to its power to any target.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Wildsear, Scouring Maw | `Enchantment spells you cast from your hand have cascade.` |  |


### Commander Cube (245 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Abuelo, Ancestral Echo | `<cost>: exile another target creature or artifact you control. return it to the battlefield under its owner's control at the beginning of the next end step.` |  |
| Aerial Extortionist | Compound gap — `Whenever ~ enters or deals combat damage to a player, exile up to <n> target nonland permanent. for as long as that card remains exiled, its owner may cast it.`; `Whenever another player casts a spell from anywhere other than their hand, draw a card.` |  |
| Agadeem's Awakening // Agadeem, the Undercrypt | `Return from your graveyard to the battlefield any number of target creature cards that each have a different mana value x or less.` |  |
| All Is Dust | `Each player sacrifices all permanents they control that are <n> or more colors.` |  |
| Anje Falkenrath | `Whenever you discard a card, if it has madness, untap ~.` |  |
| Anje's Ravager | `Whenever ~ attacks, discard your hand, then draw <n> cards.` |  |
| Answered Prayers | `Whenever a creature you control enters, you gain <n> life. if ~ isn't a creature, it becomes a <n>/<n> angel creature with flying in addition to its other types until end of turn.` |  |
| Apprentice Necromancer | `<cost>, <cost>, sacrifice ~: return target creature card from your graveyard to the battlefield. that creature gains haste. at the beginning of the next end step, sacrifice it.` |  |
| Arbaaz Mir | `Whenever ~ or another nontoken historic permanent you control enters, ~ deals <n> damage to each opponent and you gain <n> life.` |  |
| Archfiend of Spite | `Whenever a source an opponent controls deals damage to ~, that source's controller loses that much life unless they sacrifice that many permanents of their choice.` |  |
| Archon of Cruelty | `Whenever ~ enters or attacks, target opponent sacrifices a creature or planeswalker of their choice, discards a card, and loses <n> life. you draw a card and gain <n> life.` |  |
| Artificer's Dragon | `<cost>: artifact creatures you control get +<n>/+<n> until end of turn.` |  |
| Avacyn's Judgment | `~ deals <n> damage divided as you choose among any number of targets. if this spell's madness cost was paid, it deals x damage divided as you choose among those permanents and/or players instead.` |  |
| Aven Interrupter | Compound gap — `Spells your opponents cast from graveyards or from exile cost <cost> more to cast.`; `When ~ enters, exile target spell. it becomes plotted.` |  |
| Ayara, First of Locthwain | `Whenever ~ or another black creature you control enters, each opponent loses <n> life and you gain <n> life.` |  |
| Azra Oddsmaker | `At the beginning of combat on your turn, you may discard a card. if you do, choose a creature. whenever that creature deals combat damage to a player this turn, you draw <n> cards.` |  |
| Azure Fleet Admiral | `~ can't be blocked by creatures the monarch controls.` |  |
| Barad-dûr | `<cost>, <cost>: amass orcs x. activate only if a creature died this turn.` |  |
| Barrin, Tolarian Archmage | Compound gap — `At the beginning of your end step, if a permanent was put into your hand from the battlefield this turn, draw a card.`; `When ~ enters, return up to <n> other target creature or planeswalker to its owner's hand.` |  |
| Battle for Bretagard | `Iii — choose any number of artifact tokens and/or creature tokens you control with different names. for each of them, create a token that's a copy of it.` |  |
| Benevolent Offering | Compound gap — `Choose an opponent. you and that player each create <n> <n>/<n> white spirit creature tokens with flying.`; `Choose an opponent. you gain <n> life for each creature you control and that player gains <n> life for each creature they control.` |  |
| Benthic Biomancer | `Whenever <n> or more +<n>/+<n> counters are put on ~, draw a card, then discard a card.` |  |
| Black Sun's Twilight | `Up to <n> target creature gets -x/-x until end of turn. if x is <n> or more, return a creature card with mana value x or less from your graveyard to the battlefield tapped.` |  |
| Blanchwood Prowler | `When ~ enters, mill <n> cards. you may put a land card from among the cards milled this way into your hand. if you don't, put a +<n>/+<n> counter on ~.` |  |
| Blast-Furnace Hellkite | `Creatures attacking your opponents have double strike.` |  |
| Bloodtithe Harvester | `<cost>, sacrifice ~: target creature gets -x/-x until end of turn, where x is twice the number of blood tokens you control. activate only as a sorcery.` |  |
| Bone Miser | Compound gap — `Whenever you discard a creature card, create a <n>/<n> black zombie creature token.`; `Whenever you discard a land card, add <cost>.`; `Whenever you discard a noncreature, nonland card, draw a card.` |  |
| Brago, King Eternal | `Whenever ~ deals combat damage to a player, exile any number of target nonland permanents you control, then return those cards to the battlefield under their owner's control.` |  |
| Brallin, Skyshark Rider | `<cost>: target shark gains trample until end of turn.` |  |
| Call to the Netherworld | `Return target black creature card from your graveyard to your hand.` |  |
| Campus Renovation | `Return up to <n> target artifact or enchantment card from your graveyard to the battlefield. exile the top <n> cards of your library. until the end of your next turn, you may play those cards.` |  |
| Caretaker's Talent | Compound gap — `When this class becomes level <n>, create a token that's a copy of target token you control.`; `Whenever <n> or more tokens you control enter, draw a card. this ability triggers only once each turn.` |  |
| Castle Locthwain | `<cost>, <cost>: draw a card, then you lose life equal to the number of cards in your hand.` |  |
| Cat Collector | `Whenever you gain life for the first time during each of your turns, create a <n>/<n> white cat creature token.` |  |
| Celestine, the Living Saint | `At the beginning of your end step, return target creature card with mana value x or less from your graveyard to the battlefield, where x is the amount of life you gained this turn.` |  |
| Cemetery Desecrator | Compound gap — `When ~ enters or dies, exile another card from a graveyard. when you do, choose <n> —`; `• remove x counters from target permanent, where x is the mana value of the exiled card.`; `• target creature an opponent controls gets -x/-x until end of turn, where x is the mana value of the exiled card.` |  |
| Chainer, Nightmare Adept | Compound gap — `Discard a card: you may cast a creature spell from your graveyard this turn. activate only once each turn.`; `Whenever a nontoken creature you control enters, if you didn't cast it from your hand, it gains haste until your next turn.` |  |
| Chainsaw | Compound gap — `Equipped creature gets +x/+<n>, where x is the number of rev counters on ~.`; `Whenever <n> or more creatures die, put a rev counter on ~.` |  |
| Champion of Lambholt | `Creatures with power less than ~'s power can't block creatures you control.` |  |
| Champions of Minas Tirith | `At the beginning of combat on each opponent's turn, if you're the monarch, that opponent may pay <cost>, where x is the number of cards in their hand. if they don't, they can't attack you this combat.` |  |
| Chill of the Grave | `This spell costs <cost> less to cast if you control a zombie.` |  |
| Cleaver Skaab | `<cost>, <cost>, sacrifice another zombie: create <n> tokens that are copies of the sacrificed creature.` |  |
| Cloud, Midgar Mercenary | `As long as ~ is equipped, if a triggered ability of ~ or an equipment attached to it triggers, that ability triggers an additional time.` |  |
| Cool but Rude | Compound gap — `When this class becomes level <n>, search your library for a card, put it into your hand, shuffle, then discard a card at random.`; `Whenever you discard a card, this class deals <n> damage to each opponent.` |  |
| Court of Grace | `At the beginning of your upkeep, create a <n>/<n> white spirit creature token with flying. if you're the monarch, create a <n>/<n> white angel creature token with flying instead.` |  |
| Court of Ire | `At the beginning of your upkeep, ~ deals <n> damage to any target. if you're the monarch, it deals <n> damage instead.` |  |
| Crown of Gondor | `When a legendary creature you control enters, if there is no monarch, you become the monarch.` |  |
| Custodi Lich | `Whenever you become the monarch, target player sacrifices a creature of their choice.` |  |
| Daretti, Rocketeer Engineer | Compound gap — `~'s power is equal to the greatest mana value among artifacts you control.`; `Whenever ~ enters or attacks, choose target artifact card in your graveyard. you may sacrifice an artifact. if you do, return the chosen card to the battlefield.` |  |
| Dark Salvation | `Target player creates x <n>/<n> black zombie creature tokens, then up to <n> target creature gets -<n>/-<n> until end of turn for each zombie that player controls.` |  |
| Dauntless Scrapbot | `When ~ enters, exile each opponent's graveyard. create a lander token.` |  |
| Death Baron | `Skeletons you control and other zombies you control get +<n>/+<n> and have deathtouch.` |  |
| Demand Answers | `As an additional cost to cast this spell, sacrifice an artifact or discard a card.` |  |
| Diregraf Colossus | `~ enters with a +<n>/+<n> counter on it for each zombie card in your graveyard.` |  |
| Disciple of Freyalise // Garden of Freyalise | `When ~ enters, you may sacrifice another creature. if you do, you gain x life and draw x cards, where x is that creature's power.` |  |
| Disorder in the Court | `Exile x target creatures, then investigate x times. return the exiled cards to the battlefield tapped under their owners' control at the beginning of the next end step.` |  |
| Docent of Perfection // Final Iteration | `Whenever you cast an instant or sorcery spell, create a <n>/<n> blue human wizard creature token. then if you control <n> or more wizards, transform ~.` |  |
| Doctor Doom, King of Latveria | Compound gap — `At the beginning of combat on your turn, target villain you control gains menace until end of turn. it connives.`; `Whenever you discard <n> or more land cards, each opponent loses <n> life.` |  |
| Don & Leo, Problem Solvers | `At the beginning of your end step, exile up to <n> target artifact you control and up to <n> target creature you control. then return them to the battlefield under their owners' control.` |  |
| Draconic Muralists | `When ~ dies, you may search your library for a dragon card, reveal it, put it into your hand, then shuffle.` |  |
| Dragon Broodmother | `At the beginning of each upkeep, create a <n>/<n> red and green dragon creature token with flying and devour <n>.` |  |
| Dragonborn Champion | `Whenever a source you control deals <n> or more damage to a player, draw a card.` |  |
| Dragonspark Reactor | `<cost>, sacrifice ~: it deals damage equal to the number of charge counters on it to target player and that much damage to up to <n> target creature.` |  |
| Draining Whelk | `When ~ enters, counter target spell. put x +<n>/+<n> counters on ~, where x is that spell's mana value.` |  |
| Dusk Mangler | Compound gap — `As an additional cost to cast this spell, sacrifice a creature, discard a card, or pay <n> life.`; `When ~ enters, each opponent sacrifices a creature of their choice, discards a card, and loses <n> life.` |  |
| Dying to Serve | `Whenever you discard <n> or more cards, create a tapped <n>/<n> black zombie creature token. this ability triggers only once each turn.` |  |
| Earthquake Dragon | `This spell costs <cost> less to cast, where x is the total mana value of dragons you control.` |  |
| Echocasting Symposium | `Target player creates a token that's a copy of target creature you control.` |  |
| Edgar's Awakening | `When you discard this card, you may pay <cost>. when you do, return target creature card from your graveyard to your hand.` |  |
| Eerie Interlude | `Exile any number of target creatures you control. return those cards to the battlefield under their owner's control at the beginning of the next end step.` |  |
| Elenda's Hierophant | `When ~ dies, create x <n>/<n> white vampire creature tokens with lifelink, where x is its power.` |  |
| Elenda, Saint of Dusk | `As long as your life total is greater than your starting life total, ~ gets +<n>/+<n> and has menace. ~ gets an additional +<n>/+<n> as long as your life total is at least <n> greater than your starting life total.` |  |
| Elesh Norn // The Argent Etchings | `Whenever a source an opponent controls deals damage to you or a permanent you control, that source's controller loses <n> life unless they pay <cost>.` |  |
| Emberwilde Captain | `Whenever an opponent attacks you while you're the monarch, ~ deals damage to that player equal to the number of cards in their hand.` |  |
| Emeria's Call // Emeria, Shattered Skyclave | `Create <n> <n>/<n> white angel warrior creature tokens with flying. non-angel creatures you control gain indestructible until your next turn.` |  |
| Empty the Laboratory | `Sacrifice x zombies, then reveal cards from the top of your library until you reveal a number of zombie creature cards equal to the number of zombies sacrificed this way. put those cards onto the battlefield and the rest on the bottom of your library in a random order.` |  |
| Eris, Roar of the Storm | `This spell costs <cost> less to cast for each different mana value among instant and sorcery cards in your graveyard.` |  |
| Experimental Synthesizer | `When ~ enters or leaves the battlefield, exile the top card of your library. until end of turn, you may play that card.` |  |
| Ezuri, Claw of Progress | Compound gap — `At the beginning of combat on your turn, put x +<n>/+<n> counters on another target creature you control, where x is the number of experience counters you have.`; `Whenever a creature you control with power <n> or less enters, you get an experience counter.` |  |
| Fall from Favor | `Enchanted creature doesn't untap during its controller's untap step unless that player is the monarch.` |  |
| Fallen Shinobi | `Whenever ~ deals combat damage to a player, that player exiles the top <n> cards of their library. until end of turn, you may play those cards without paying their mana costs.` |  |
| Fateful Absence | `Destroy target creature or planeswalker. its controller investigates.` |  |
| Fatestitcher | `<cost>: you may tap or untap another target permanent.` |  |
| Fear of Impostors | `When ~ enters, counter target spell. its controller manifests dread.` |  |
| Felidar Retreat | Compound gap — `Whenever a land you control enters, choose <n> —`; `• create a <n>/<n> white cat beast creature token.`; `• put a +<n>/+<n> counter on each creature you control. those creatures gain vigilance until end of turn.` |  |
| Filigree Vector | `When ~ enters, put a +<n>/+<n> counter on each of any number of target creatures and a charge counter on each of any number of target artifacts.` |  |
| Firespitter Whelp | `Whenever you cast a noncreature or dragon spell, ~ deals <n> damage to each opponent.` |  |
| Foe-Razer Regent | `Whenever a creature you control fights, put <n> +<n>/+<n> counters on it at the beginning of the next end step.` |  |
| From Under the Floorboards | `Create <n> tapped <n>/<n> black zombie creature tokens and you gain <n> life. if this spell's madness cost was paid, instead create x of those tokens and you gain x life.` |  |
| From the Catacombs | `Put target creature card from a graveyard onto the battlefield under your control with a corpse counter on it. you take the initiative. if that creature would leave the battlefield, exile it instead of putting it anywhere else.` |  |
| Geralf, Visionary Stitcher | `<cost>, <cost>, sacrifice another nontoken creature: create an x/x blue zombie creature token, where x is the sacrificed creature's toughness.` |  |
| Geralf, the Fleshwright | Compound gap — `Whenever a zombie you control enters, put a +<n>/+<n> counter on it for each other zombie that entered the battlefield under your control this turn.`; `Whenever you cast a spell during your turn other than your first spell that turn, create a <n>/<n> blue and black zombie rogue creature token.` |  |
| Gilraen, Dúnedain Protector | `<cost>, <cost>: exile another target creature you control. you may return that card to the battlefield under its owner's control. if you don't, at the beginning of the next end step, return that card to the battlefield under its owner's control with a vigilance counter and a lifelink counter on it.` |  |
| Gisa and Geralf | `Once during each of your turns, you may cast a zombie creature spell from your graveyard.` |  |
| Gisa, the Hellraiser | Compound gap — `Skeletons and zombies you control get +<n>/+<n> and have menace.`; `Whenever you commit a crime, create <n> tapped <n>/<n> blue and black zombie rogue creature tokens. this ability triggers only once each turn.` |  |
| Githzerai Monk | `When ~ enters, tap all creatures you don't control.` |  |
| Glimmer Lens | `Whenever equipped creature and at least <n> other creature attack, draw a card.` |  |
| Glimpse the Impossible | `Exile the top <n> cards of your library. you may play those cards this turn. at the beginning of the next end step, if any of those cards remain exiled, put them into your graveyard, then create a <n>/<n> colorless eldrazi spawn creature token for each card put into your graveyard this way. those tokens have ~` |  |
| Grave Scrabbler | `When ~ enters, if its madness cost was paid, you may return target creature card from a graveyard to its owner's hand.` |  |
| Gumdrop Poisoner // Tempt with Treats | `When ~ enters, up to <n> target creature gets -x/-x until end of turn, where x is the amount of life you gained this turn.` |  |
| Hagra Mauling // Hagra Broodpit | `This spell costs <cost> less to cast if an opponent controls no basic lands.` |  |
| Havengul Lich | `<cost>: you may cast target creature card in a graveyard this turn. when you cast it this turn, ~ gains all activated abilities of that card until end of turn.` |  |
| Havengul Runebinder | `<cost>, <cost>, exile a creature card from your graveyard: create a <n>/<n> black zombie creature token, then put a +<n>/+<n> counter on each zombie creature you control.` |  |
| Highcliff Felidar | `When ~ enters, for each opponent, choose a creature with the greatest power among creatures that player controls. destroy those creatures.` |  |
| Highway Robbery | `You may discard a card or sacrifice a land. if you do, draw <n> cards.` |  |
| Hordewing Skaab | `Whenever <n> or more zombies you control deal combat damage to <n> or more of your opponents, you may draw cards equal to the number of opponents dealt damage this way. if you do, discard that many cards.` |  |
| Hostile Investigator | `Whenever <n> or more players discard <n> or more cards, investigate. this ability triggers only once each turn.` |  |
| Ignite the Future | `Exile the top <n> cards of your library. until the end of your next turn, you may play those cards. if this spell was cast from a graveyard, you may play cards this way without paying their mana costs.` |  |
| Immolating Gyre | `~ deals x damage to each creature and planeswalker you don't control, where x is the number of instant and sorcery cards in your graveyard.` |  |
| Improvisation Capstone | `Exile cards from the top of your library until you exile cards with total mana value <n> or greater. you may cast any number of spells from among them without paying their mana costs.` |  |
| Increasing Devotion | `Create <n> <n>/<n> white human creature tokens. if this spell was cast from a graveyard, create <n> of those tokens instead.` |  |
| Ingenious Artillerist | `Whenever <n> or more artifacts you control enter, ~ deals that much damage to each opponent.` |  |
| Inspiration from Beyond | `Mill <n> cards, then return an instant or sorcery card from your graveyard to your hand.` |  |
| Inti, Seneschal of the Sun | `Whenever you discard <n> or more cards, exile the top card of your library. you may play that card until your next end step.` |  |
| Invasion of Tarkir // Defiant Thundermaw | `When ~ enters, reveal any number of dragon cards from your hand. when you do, ~ deals x plus <n> damage to any other target, where x is the number of cards revealed this way.` |  |
| Ironsoul Enforcer | `Whenever ~ or a commander you control attacks alone, return target artifact card from your graveyard to the battlefield.` |  |
| Isareth the Awakener | `Whenever ~ attacks, you may pay <cost>. when you do, return target creature card with mana value x from your graveyard to the battlefield with a corpse counter on it. if that creature would leave the battlefield, exile it instead of putting it anywhere else.` |  |
| Izoni, Thousand-Eyed | `When ~ enters, create a <n>/<n> black and green insect creature token for each creature card in your graveyard.` |  |
| Jalira, Master Polymorphist | `<cost>, <cost>, sacrifice another creature: reveal cards from the top of your library until you reveal a nonlegendary creature card. put that card onto the battlefield and the rest on the bottom of your library in a random order.` |  |
| Jin-Gitaxias // The Great Synthesis | `Whenever you cast a noncreature spell with mana value <n> or greater, draw a card.` |  |
| Jinnie Fay, Jetmir's Second | `If you would create <n> or more tokens, you may instead create that many <n>/<n> green cat creature tokens with haste or that many <n>/<n> green dog creature tokens with vigilance.` |  |
| Jugan Defends the Temple // Remnant of the Rising Star | `I — create a <n>/<n> green human monk creature token with ~` |  |
| Juvenile Mist Dragon | `When ~ enters, for each opponent, tap up to <n> target creature that player controls. each of those creatures doesn't untap during its controller's next untap step.` |  |
| Kabira Takedown // Kabira Plateau | `~ deals damage equal to the number of creatures you control to target creature or planeswalker.` |  |
| Kitesail Larcenist | `When ~ enters, for each player, choose up to <n> other target artifact or creature that player controls. for as long as ~ remains on the battlefield, the chosen permanents become treasure artifacts with ~ and lose all other abilities.` |  |
| Krenko, Baron of Tin Street | `<cost>, sacrifice an artifact: put a +<n>/+<n> counter on each goblin you control.` |  |
| Lluwen, Imperfect Naturalist | Compound gap — `<cost>, <cost>, discard a land card: create a <n>/<n> black and green worm creature token for each land card in your graveyard.`; `When ~ enters, mill <n> cards, then you may put a creature or land card from among the milled cards on top of your library.` |  |
| Lonis, Genetics Expert | Compound gap — `Whenever <n> or more +<n>/+<n> counters are put on ~, investigate that many times.`; `Whenever you sacrifice a clue, put a +<n>/+<n> counter on another target creature you control.` |  |
| Losheel, Clockwork Scholar | Compound gap — `Prevent all combat damage that would be dealt to attacking artifact creatures you control.`; `Whenever <n> or more artifact creatures you control enter, draw a card. this ability triggers only once each turn.` |  |
| Lotleth Giant | `When ~ enters, it deals <n> damage to target opponent for each creature card in your graveyard.` |  |
| Loyal Drake | `At the beginning of combat on your turn, if you control your commander, draw a card.` |  |
| Loyal Guardian | `At the beginning of combat on your turn, if you control your commander, put a +<n>/+<n> counter on each creature you control.` |  |
| Loyal Subordinate | `At the beginning of combat on your turn, if you control your commander, each opponent loses <n> life.` |  |
| Loyal Unicorn | `At the beginning of combat on your turn, if you control your commander, prevent all combat damage that would be dealt to creatures you control this turn. other creatures you control gain vigilance until end of turn.` |  |
| Ludevic, Necrogenius // Olag, Ludevic's Hubris | `<cost>, exile x creature cards from your graveyard: transform ~. x can't be <n>. activate only as a sorcery.` |  |
| Magmatic Channeler | Compound gap — `<cost>, discard a card: exile the top <n> cards of your library, then choose <n> of them. you may play that card this turn.`; `As long as there are <n> or more instant and/or sorcery cards in your graveyard, ~ gets +<n>/+<n>.` |  |
| Malevolent Rumble | `Reveal the top <n> cards of your library. you may put a permanent card from among them into your hand. put the rest into your graveyard. create a <n>/<n> colorless eldrazi spawn creature token with ~` |  |
| Mana Sculpt | `Counter target spell. if you control a wizard, add an amount of <cost> equal to the amount of mana spent to cast that spell at the beginning of your next main phase.` |  |
| Masked Vandal | `When ~ enters, you may exile a creature card from your graveyard. if you do, exile target artifact or enchantment an opponent controls.` |  |
| Master Biomancer | `Each other creature you control enters with a number of additional +<n>/+<n> counters on it equal to ~'s power and as a mutant in addition to its other types.` |  |
| Master of Death | `At the beginning of your upkeep, if this card is in your graveyard, you may pay <n> life. if you do, return it to your hand.` |  |
| Meteor Blast | `~ deals <n> damage to each of x targets.` |  |
| Mistmeadow Witch | `<cost>: exile target creature. return that card to the battlefield under its owner's control at the beginning of the next end step.` |  |
| Monstrous Onslaught | `~ deals x damage divided as you choose among any number of target creatures, where x is the greatest power among creatures you control as you cast this spell.` |  |
| Moonstone, Harsh Mistress | `Whenever you discard a card, you may exile that card from your graveyard. if you do, until the end of your next turn, you may play that card.` |  |
| Moonveil Regent | Compound gap — `When ~ dies, it deals x damage to any target, where x is the number of colors among permanents you control.`; `Whenever you cast a spell, you may discard your hand. if you do, draw a card for each of that spell's colors.` |  |
| Moria Scavenger | `<cost>, discard a card: draw a card. if the discarded card was a creature card, amass orcs <n>.` |  |
| Nahiri's Resolve | `At the beginning of your end step, exile any number of nontoken artifacts and/or creatures you control. return those cards to the battlefield under their owner's control at the beginning of your next upkeep.` |  |
| Necrogoyf | `~'s power is equal to the number of creature cards in all graveyards.` |  |
| Nighthawk Scavenger | `~'s power is equal to <n> plus the number of card types among cards in your opponents' graveyards.` |  |
| Old Rutstein | `When ~ enters and at the beginning of your upkeep, mill a card. if a land card is milled this way, create a treasure token. if a creature card is milled this way, create a <n>/<n> green insect creature token. if a noncreature, nonland card is milled this way, create a blood token.` |  |
| Olivia, Mobilized for War | `Whenever another creature you control enters, you may discard a card. if you do, put a +<n>/+<n> counter on that creature, it gains haste until end of turn, and it becomes a vampire in addition to its other types.` |  |
| Organ Hoarder | `When ~ enters, look at the top <n> cards of your library, then put <n> of them into your hand and the rest into your graveyard.` |  |
| Osgir, the Reconstructor | `<cost>, <cost>, exile an artifact card with mana value x from your graveyard: create <n> tokens that are copies of the exiled card. activate only as a sorcery.` |  |
| Overcharged Amalgam | `When ~ exploits a creature, counter target spell, activated ability, or triggered ability.` |  |
| Parting Gust | `Exile target nontoken creature. if the gift wasn't promised, return that card to the battlefield under its owner's control with a +<n>/+<n> counter on it at the beginning of the next end step.` |  |
| Party Thrasher | Compound gap — `At the beginning of your first main phase, you may discard a card. if you do, exile the top <n> cards of your library, then choose <n> of them. you may play that card this turn.`; `Noncreature spells you cast from exile have convoke.` |  |
| Peel from Reality | `Return target creature you control and target creature you don't control to their owners' hands.` |  |
| Pensive Professor | `Whenever <n> or more +<n>/+<n> counters are put on ~, draw a card.` |  |
| Phelia, Exuberant Shepherd | `Whenever ~ attacks, exile up to <n> other target nonland permanent. at the beginning of the next end step, return that card to the battlefield under its owner's control. if it entered under your control, put a +<n>/+<n> counter on ~.` |  |
| Phyrexian Delver | `When ~ enters, return target creature card from your graveyard to the battlefield. you lose life equal to that card's mana value.` |  |
| Pink Horror | `Split — when ~ dies, create <n> <n>/<n> blue and red demon horror creature tokens named blue horror with ~` |  |
| Portal to Phyrexia | `At the beginning of your upkeep, put target creature card from a graveyard onto the battlefield under your control. it's a phyrexian in addition to its other types.` |  |
| Precognitive Perception | `If you cast this spell during your main phase, instead scry <n>, then draw <n> cards.` |  |
| Predatory Rampage | `Creatures you control get +<n>/+<n> until end of turn. each creature your opponents control blocks this turn if able.` |  |
| Prosper, Tome-Bound | Compound gap — `Mystic arcanum — at the beginning of your end step, exile the top card of your library. until the end of your next turn, you may play that card.`; `Pact boon — whenever you play a card from exile, create a treasure token.` |  |
| Puppet Master, String Puller | Compound gap — `Whenever <n> or more goaded creatures deal combat damage to <n> of your opponents, create a treasure token.`; `Whenever you attack, goad target creature an opponent controls. it can't block this turn.` |  |
| Queen Allenal of Ruadach | `If <n> or more creature tokens would be created under your control, those tokens plus a <n>/<n> white soldier creature token are created instead.` |  |
| Ravenous Gigantotherium | `When ~ enters, it deals x damage divided as you choose among up to x target creatures, where x is its power. each of those creatures deals damage equal to its power to ~.` |  |
| Ravenous Robots | `<cost>, <cost>: creature tokens you control gain haste until end of turn.` |  |
| Ravenous Rotbelly | `When ~ enters, you may sacrifice up to <n> zombies. when you sacrifice <n> or more zombies this way, each opponent sacrifices that many creatures of their choice.` |  |
| Realm-Scorcher Hellkite | `When ~ enters, if it was bargained, add <n> mana in any combination of colors.` |  |
| Reconstruct History | `Return up to <n> target artifact card, up to <n> target enchantment card, up to <n> target instant card, up to <n> target sorcery card, and up to <n> target planeswalker card from your graveyard to your hand.` |  |
| Red Dragon | `Fire breath — when ~ enters, it deals <n> damage to each opponent.` |  |
| Revenge of the Rats | `Create a tapped <n>/<n> black rat creature token for each creature card in your graveyard.` |  |
| Rhys the Redeemed | `<cost>, <cost>: for each creature token you control, create a token that's a copy of that creature.` |  |
| Riptide Gearhulk | `When ~ enters, for each opponent, put up to <n> target nonland permanent that player controls into its owner's library third from the top.` |  |
| Rise of the Witch-king | `Each player sacrifices a creature of their choice. if you sacrificed a creature this way, you may return another permanent card from your graveyard to the battlefield.` |  |
| Roadside Reliquary | `<cost>, <cost>, sacrifice ~: draw a card if you control an artifact. draw a card if you control an enchantment.` |  |
| Sage of Fables | `Each other wizard creature you control enters with an additional +<n>/+<n> counter on it.` |  |
| Sarevok's Tome | `<cost>, <cost>: exile cards from the top of your library until you exile a nonland card. you may cast that card without paying its mana cost. activate only if you've completed a dungeon.` |  |
| Scampering Surveyor | `When ~ enters, search your library for a basic land card or cave card, put it onto the battlefield tapped, then shuffle.` |  |
| Scavenged Brawler | `<cost>, exile this card from your graveyard: choose target creature. put <n> +<n>/+<n> counters, a flying counter, a vigilance counter, a trample counter, and a lifelink counter on that creature. activate only as a sorcery.` |  |
| Scourge of Valkas | `Whenever ~ or another dragon you control enters, it deals x damage to any target, where x is the number of dragons you control.` |  |
| Sea Gate Restoration // Sea Gate, Reborn | `Draw cards equal to the number of cards in your hand plus <n>. you have no maximum hand size for the rest of the game.` |  |
| Seasoned Dungeoneer | `Whenever you attack, target attacking cleric, rogue, warrior, or wizard gains protection from creatures until end of turn. it explores.` |  |
| Seasoned Pyromancer | `When ~ enters, discard <n> cards, then draw <n> cards. for each nonland card discarded this way, create a <n>/<n> red elemental creature token.` |  |
| Securitron Squadron | `Whenever a creature token you control enters, put a +<n>/+<n> counter on it.` |  |
| Sentinel Sarah Lyons | Compound gap — `As long as an artifact entered the battlefield under your control this turn, creatures you control get +<n>/+<n>.`; `Whenever ~ and at least <n> other creatures attack, ~ deals damage equal to the number of artifacts you control to target player.` |  |
| Sephara, Sky's Blade | Compound gap — `Other creatures you control with flying have indestructible.`; `You may pay <cost> and tap <n> untapped creatures you control with flying rather than pay this spell's mana cost.` |  |
| Shadowgrange Archfiend | `When ~ enters, each opponent sacrifices a creature with the greatest power among creatures they control. you gain life equal to the greatest power among creatures sacrificed this way.` |  |
| Sharktocrab | `Whenever <n> or more +<n>/+<n> counters are put on ~, tap target creature an opponent controls. that creature doesn't untap during its controller's next untap step.` |  |
| Sheoldred // The True Scriptures | `When ~ enters, each opponent sacrifices a nontoken creature or planeswalker of their choice.` |  |
| Signature Slam | `Put a +<n>/+<n> counter on target creature you control, then each modified creature you control deals damage equal to its power to target creature you don't control.` |  |
| Simic Manipulator | `<cost>, remove <n> or more +<n>/+<n> counters from ~: gain control of target creature with power less than or equal to the number of +<n>/+<n> counters removed this way.` |  |
| Slash the Ranks | `Destroy all creatures and planeswalkers except for commanders.` |  |
| Slimefoot and Squee | `<cost>, sacrifice a saproling: return this card and up to <n> other target creature card from your graveyard to the battlefield. activate only as a sorcery.` |  |
| Smoldering Egg // Ashmouth Dragon | `Whenever you cast an instant or sorcery spell, put a number of ember counters on ~ equal to the amount of mana spent to cast that spell. then if ~ has <n> or more ember counters on it, remove them and transform ~.` |  |
| Smuggler's Surprise | Compound gap — `+ <cost> — creatures you control with power <n> or greater gain hexproof and indestructible until end of turn.`; `+ <cost> — mill <n> cards. you may put up to <n> creature and/or land cards from among the milled cards into your hand.`; `+ <cost> — you may put up to <n> creature cards from your hand onto the battlefield.` |  |
| Soulherder | `Whenever a creature is exiled from the battlefield, put a +<n>/+<n> counter on ~.` |  |
| Spear of Heliod | `<cost>, <cost>: destroy target creature that dealt damage to you this turn.` |  |
| Spinerock Tyrant | `Whenever you cast an instant or sorcery spell with a single target, you may copy it. if you do, those spells gain wither. you may choose new targets for the copy.` |  |
| Splitskin Doll | `When ~ enters, draw a card. then discard a card unless you control another creature with power <n> or less.` |  |
| Starfall Invocation | `Destroy all creatures. if the gift was promised, return a creature card put into your graveyard this way to the battlefield under your control.` |  |
| Steel Seraph | `At the beginning of combat on your turn, target creature you control gains your choice of flying, vigilance, or lifelink until end of turn.` |  |
| Stromkirk Occultist | `Whenever ~ deals combat damage to a player, exile the top card of your library. until end of turn, you may play that card.` |  |
| Surly Badgersaur | Compound gap — `Whenever you discard a creature card, put a +<n>/+<n> counter on ~.`; `Whenever you discard a land card, create a treasure token.`; `Whenever you discard a noncreature, nonland card, ~ fights up to <n> target creature you don't control.` |  |
| Synchronized Charge | `Distribute <n> +<n>/+<n> counters among <n> or <n> target creatures you control. creatures you control with counters on them gain vigilance and trample until end of turn.` |  |
| Teleportation Circle | `At the beginning of your end step, exile up to <n> target artifact or creature you control, then return that card to the battlefield under its owner's control.` |  |
| The Eternal Wanderer | Compound gap — `+<n>: exile up to <n> target artifact or creature. return that card to the battlefield under its owner's control at the beginning of that player's next end step.`; `No more than <n> creature can attack ~ each combat.`; `−<n>: for each player, choose a creature that player controls. each player sacrifices all creatures they control not chosen this way.` |  |
| The Ooze | Compound gap — `<cost>: exile target card from a graveyard. create a mutagen token.`; `Whenever a creature you control with a +<n>/+<n> counter on it leaves the battlefield, create a mutagen token for each +<n>/+<n> counter on it.` |  |
| The Raven Man | `At the beginning of each end step, if a player discarded a card this turn, create a <n>/<n> black bird creature token with flying and ~` |  |
| Thing in the Ice // Awoken Horror | `Whenever you cast an instant or sorcery spell, remove an ice counter from ~. then if it has no ice counters on it, transform it.` |  |
| Thousand Moons Smithy // Barracks of the Thousand | Compound gap — `At the beginning of your first main phase, you may tap <n> untapped artifacts and/or creatures you control. if you do, transform ~.`; `When ~ enters, create a white gnome soldier artifact creature token with ~` |  |
| Thrakkus the Butcher | `Whenever ~ attacks, double the power of each dragon you control until end of turn.` |  |
| Three Steps Ahead | Compound gap — `+ <cost> — counter target spell.`; `+ <cost> — create a token that's a copy of target artifact or creature you control.`; `+ <cost> — draw <n> cards, then discard a card.` |  |
| Thrull Parasite | `<cost>, pay <n> life: remove a counter from target nonland permanent.` |  |
| Thunderhawk Gunship | `Whenever ~ attacks, attacking creatures you control gain flying until end of turn.` |  |
| Tivash, Gloom Summoner | `At the beginning of your end step, if you gained life this turn, you may pay x life, where x is the amount of life you gained this turn. if you do, create an x/x black demon creature token with flying.` |  |
| Toby, Beastie Befriender | Compound gap — `As long as you control <n> or more creature tokens, creature tokens you control have flying.`; `When ~ enters, create a <n>/<n> white beast creature token with ~` |  |
| Tom Bombadil | Compound gap — `As long as there are <n> or more lore counters among sagas you control, ~ has hexproof and indestructible.`; `Whenever the final chapter ability of a saga you control resolves, reveal cards from the top of your library until you reveal a saga card. put that card onto the battlefield and the rest on the bottom of your library in a random order. this ability triggers only once each turn.` |  |
| Tomb of Horrors Adventurer | `Whenever you cast your second spell each turn, copy it. if you've completed a dungeon, copy that spell twice instead. you may choose new targets for the copies.` |  |
| Transmogrifying Wand | `<cost>, <cost>, remove a charge counter from ~: destroy target creature. its controller creates a <n>/<n> white ox creature token. activate only as a sorcery.` |  |
| Twilight Prophet | `At the beginning of your upkeep, if you have the city's blessing, reveal the top card of your library and put it into your hand. each opponent loses x life and you gain x life, where x is that card's mana value.` |  |
| Ugin, the Spirit Dragon | Compound gap — `−<n>: you gain <n> life, draw <n> cards, then put up to <n> permanent cards from your hand onto the battlefield.`; `−x: exile each permanent with mana value x or less that's <n> or more colors.` |  |
| Undead Butler | `When ~ dies, you may exile it. when you do, return target creature card from your graveyard to your hand.` |  |
| Unexplained Absence | `For each player, exile up to <n> target nonland permanent that player controls. for each permanent exiled this way, its controller cloaks the top card of their library.` |  |
| Unholy Heat | `~ deals <n> damage instead if there are <n> or more card types among cards in your graveyard.` |  |
| Urabrask // The Great Work | `<cost>: exile ~, then return it to the battlefield transformed under its owner's control. activate only as a sorcery and only if you've cast <n> or more instant and/or sorcery spells this turn.` |  |
| Virtue of Knowledge // Vantress Visions | `If a permanent entering causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.` |  |
| Virtue of Loyalty // Ardenvale Fealty | `At the beginning of your end step, put a +<n>/+<n> counter on each creature you control. untap those creatures.` |  |
| Virtue of Strength // Garenbrig Growth | `If you tap a basic land for mana, it produces <n> times as much of that mana instead.` |  |
| Vizkopa Guildmage | `<cost>: whenever you gain life this turn, each opponent loses that much life.` |  |
| Voracious Fell Beast | `When ~ enters, each opponent sacrifices a creature of their choice. create a food token for each creature sacrificed this way.` |  |
| Warden of the Grove | `Whenever another nontoken creature you control enters, it endures x, where x is the number of counters on ~.` |  |
| White Plume Adventurer | `At the beginning of each opponent's upkeep, untap a creature you control. if you've completed a dungeon, untap all creatures you control instead.` |  |
| Wildfire Devils | `When ~ enters and at the beginning of your upkeep, choose a player at random. that player exiles an instant or sorcery card from their graveyard. copy that card. you may cast the copy without paying its mana cost.` |  |
| Wilhelt, the Rotcleaver | `Whenever another zombie you control dies, if it didn't have decayed, create a <n>/<n> black zombie creature token with decayed.` |  |
| Windswift Slice | `Target creature you control deals damage equal to its power to target creature you don't control. create a number of <n>/<n> green elf warrior creature tokens equal to the amount of excess damage dealt this way.` |  |
| Wrathful Red Dragon | `Whenever a dragon you control is dealt damage, it deals that much damage to any target that isn't a dragon.` |  |
| Y'shtola Rhul | `At the beginning of your end step, exile target creature you control, then return it to the battlefield under its owner's control. then if it's the first end step of the turn, there is an additional end step after this step.` |  |
| Zameck Guildmage | `<cost>: this turn, each creature you control enters with an additional +<n>/+<n> counter on it.` |  |
| Zegana, Utopian Speaker | `When ~ enters, if you control another creature with a +<n>/+<n> counter on it, draw a card.` |  |
| Zombie Apocalypse | `Return all zombie creature cards from your graveyard to the battlefield tapped, then destroy all humans.` |  |
| Zul Ashur, Lich Lord | `<cost>: you may cast target zombie creature card from your graveyard this turn.` |  |


### Counter Blitz - Final Fantasy Commander (35 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Auron, Venerated Guardian | `Whenever ~ attacks, put a +<n>/+<n> counter on it. when you do, exile target creature defending player controls with power less than ~'s power until ~ leaves the battlefield.` |  |
| Blitzball Stadium | `<cost>, <cost>: until end of turn, target creature gains ~ and it can't be blocked this turn.` |  |
| Bred for the Hunt | `Whenever a creature you control with a +<n>/+<n> counter on it deals combat damage to a player, you may draw a card.` |  |
| Chasm Skulker | `When ~ dies, create x <n>/<n> blue squid creature tokens with islandwalk, where x is the number of +<n>/+<n> counters on ~.` | Also uncovered in: Peace Offering - Bloomburrow Commander |
| Chocobo Knights | `Whenever you attack, creatures you control with counters on them gain double strike until end of turn.` |  |
| Damning Verdict | `Destroy all creatures with no counters on them.` |  |
| Endless Detour | `The owner of target spell, nonland permanent, or card in a graveyard puts it on their choice of the top or bottom of their library.` |  |
| Fathom Mage | `Whenever a +<n>/+<n> counter is put on ~, you may draw a card.` | Also uncovered in: Commander Cube |
| Fight Rigging | `At the beginning of combat on your turn, put a +<n>/+<n> counter on target creature you control. then if you control a creature with power <n> or greater, you may play the exiled card without paying its mana cost.` | Also uncovered in: Commander Cube |
| Forge of Heroes | `<cost>: choose target commander that entered this turn. put a +<n>/+<n> counter on it if it's a creature and a loyalty counter on it if it's a planeswalker.` |  |
| Gatta and Luzzu | `When ~ enters, choose target creature you control. if damage would be dealt to that creature this turn, prevent that damage and put that many +<n>/+<n> counters on it.` |  |
| Generous Patron | `Whenever you put <n> or more counters on a creature you don't control, draw a card.` |  |
| Inspiring Call | `Draw a card for each creature you control with a +<n>/+<n> counter on it. those creatures gain indestructible until end of turn.` | Also uncovered in: Commander Cube, Kodama |
| Kimahri, Valiant Guardian | `At the beginning of combat on your turn, put a +<n>/+<n> counter on ~ and tap target creature an opponent controls. then you may have ~ become a copy of that creature, except its name is ~ and it has vigilance and this ability.` |  |
| Lord Jyscal Guado | `At the beginning of each end step, if you put a counter on a creature this turn, investigate.` |  |
| Lulu, Stern Guardian | `Whenever an opponent attacks you, choose target creature attacking you. put a stun counter on that creature.` |  |
| Luminous Broodmoth | `Whenever a creature you control without flying dies, return it to the battlefield under its owner's control with a flying counter on it.` | Also uncovered in: Family Matters - Bloomburrow Commander |
| Maester Seymour | Compound gap — `<cost>: monstrosity x, where x is the number of counters among creatures you control.`; `At the beginning of combat on your turn, put a number of +<n>/+<n> counters equal to ~'s power on another target creature you control.` |  |
| Protection Magic | `Put a shield counter on each of up to <n> target creatures.` | Also uncovered in: Hope to the last |
| Rampant Rejuvenator | `When ~ dies, search your library for up to x basic land cards, where x is ~'s power, put them onto the battlefield, then shuffle.` |  |
| Resourceful Defense | Compound gap — `<cost>: move any number of counters from target permanent you control onto a second target permanent you control.`; `Whenever a permanent you control leaves the battlefield, if it had counters on it, put those counters on target permanent you control.` | Also uncovered in: Counter Intelligence - Edge of Eternities Commander Deck |
| Rikku, Resourceful Guardian | Compound gap — `<cost>, <cost>: move a counter from target creature an opponent controls onto target creature you control. activate only as a sorcery.`; `Whenever you put <n> or more counters on a creature, until end of turn, that creature can't be blocked by creatures your opponents control.` | Also uncovered in: Commander Cube |
| Scholar of New Horizons | `<cost>, remove a counter from a permanent you control: search your library for a plains card and reveal it. if an opponent controls more lands than you, you may put that card onto the battlefield tapped. if you don't put the card onto the battlefield, put it into your hand. then shuffle.` |  |
| Shelinda, Yevon Acolyte | `Whenever another creature you control enters, put a +<n>/+<n> counter on that creature if its power is less than ~'s power. otherwise, put a +<n>/+<n> counter on ~.` |  |
| Sin, Unending Cataclysm | Compound gap — `As ~ enters, remove all counters from any number of artifacts, creatures, and enchantments. ~ enters with x +<n>/+<n> counters on it, where x is twice the number of counters removed this way.`; `When ~ dies, put its counters on target creature you control, then shuffle this card into its owner's library.` |  |
| Summon: Ixion | Compound gap — `I — aerospark — exile target creature an opponent controls until this saga leaves the battlefield.`; `Ii, iii — put a +<n>/+<n> counter on each of up to <n> target creatures you control. you gain <n> life.` |  |
| Summon: Magus Sisters | Compound gap — `I, ii, iii — choose <n> at random —`; `• combine powers! — put <n> +<n>/+<n> counters on target creature.`; `• defense! — put a shield counter on target creature. you gain <n> life.`; `• fight! — ~ fights up to <n> target creature an opponent controls.` |  |
| Summon: Valefor | `I — sonic wings — each opponent chooses a creature with the greatest mana value among creatures they control. return those creatures to their owners' hands.` |  |
| Summon: Yojimbo | Compound gap — `I — exile target artifact, enchantment, or tapped creature an opponent controls.`; `Ii, iii — until your next turn, creatures can't attack you unless their controller pays <cost> for each of those creatures.`; `Iv — create x treasure tokens, where x is the number of opponents who control a creature with power <n> or greater.` |  |
| Summoner's Sending | `At the beginning of your end step, you may exile target creature card from a graveyard. if you do, create a <n>/<n> white spirit creature token with flying. put a +<n>/+<n> counter on it if the exiled card's mana value is <n> or greater.` |  |
| Tidus, Yuna's Guardian | Compound gap — `At the beginning of combat on your turn, you may move a counter from target creature you control onto a second target creature you control.`; `Whenever <n> or more creatures you control with counters on them deal combat damage to a player, you may draw a card and proliferate. do this only once each turn.` |  |
| Together Forever | `<cost>: choose target creature with a counter on it. when that creature dies this turn, return that card to its owner's hand.` | Also uncovered in: Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck |
| Tromell, Seymour's Butler | Compound gap — `<cost>, <cost>: proliferate x times, where x is the number of nontoken creatures you control that entered this turn.`; `Each other nontoken creature you control enters with an additional +<n>/+<n> counter on it.` |  |
| Wakka, Devoted Guardian | Compound gap — `At the beginning of your end step, if a counter was put on ~ this turn, put a +<n>/+<n> counter on each other creature you control.`; `Whenever ~ deals combat damage to a player, destroy up to <n> target artifact that player controls and put a +<n>/+<n> counter on ~.` |  |
| Yuna, Grand Summoner | `Whenever another permanent you control dies, if it had <n> or more counters on it, you may put that number of +<n>/+<n> counters on target creature.` |  |


### Counter Intelligence - Edge of Eternities Commander Deck (20 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Alibou, Ancient Witness | `Whenever <n> or more artifact creatures you control attack, ~ deals x damage to any target and you scry x, where x is the number of tapped artifacts you control.` | Also uncovered in: Commander Cube |
| Cyberdrive Awakener | `When ~ enters, each noncreature artifact you control becomes a <n>/<n> artifact creature until end of turn.` | Also uncovered in: Shorikai Vehicles |
| Darksteel Reactor | `When ~ has twenty or more charge counters on it, you win the game.` |  |
| Deepglow Skate | `When ~ enters, double the number of each kind of counter on any number of target permanents.` | Also uncovered in: Commander Cube |
| Depthshaker Titan | Compound gap — `Each artifact creature you control has melee, trample, and haste.`; `When ~ enters, any number of target noncreature artifacts you control become <n>/<n> artifact creatures. sacrifice them at the beginning of the next end step.` |  |
| Dispatch | `If you control <n> or more artifacts, exile that creature.` | Also uncovered in: Commander Cube, Limit Break - Final Fantasy Commander |
| Empowered Autogenerator | `<cost>: put a charge counter on ~. add x mana of any <n> color, where x is the number of charge counters on ~.` |  |
| Emry, Lurker of the Loch | `<cost>: choose target artifact card in your graveyard. you may cast that card this turn.` | Also uncovered in: Shorikai Vehicles |
| Inspirit, Flagship Vessel | `At the beginning of combat on your turn, put your choice of a +<n>/+<n> counter or <n> charge counters on up to <n> other target artifact.` |  |
| Lux Artillery | Compound gap — `At the beginning of your end step, if there are thirty or more counters among artifacts and creatures you control, ~ deals <n> damage to each opponent.`; `Whenever you cast an artifact creature spell, it gains sunburst.` |  |
| Moxite Refinery | Compound gap — `<cost>, <cost>, remove x counters from an artifact or creature you control: choose <n>. activate only as a sorcery.`; `• put x +<n>/+<n> counters on target creature.`; `• put x charge counters on target artifact.` |  |
| Patrolling Peacemaker | `Whenever an opponent commits a crime, proliferate.` |  |
| Ripples of Potential | `Proliferate, then choose any number of permanents you control that had a counter put on them this way. those permanents phase out.` | Also uncovered in: Commander Cube |
| Soul-Guide Lantern | `<cost>, sacrifice ~: exile each opponent's graveyard.` | Also uncovered in: Living Energy - Aetherdrift Commander |
| Steel Overseer | `<cost>: put a +<n>/+<n> counter on each artifact creature you control.` | Also uncovered in: Commander Cube |
| Tekuthal, Inquiry Dominus | Compound gap — `<cost>, remove <n> counters from among other artifacts, creatures, and planeswalkers you control: put an indestructible counter on ~.`; `If you would proliferate, proliferate twice instead.` |  |
| The Mycosynth Gardens | `<cost>, <cost>: ~ becomes a copy of target nontoken artifact you control with mana value x.` | Also uncovered in: Commander Cube |
| Thirst for Knowledge | `Draw <n> cards. then discard <n> cards unless you discard an artifact card.` |  |
| Threefold Thunderhulk | `Whenever ~ enters or attacks, create a number of <n>/<n> colorless gnome artifact creature tokens equal to its power.` | Also uncovered in: Commander Cube |
| Wake the Past | `Return all artifact cards from your graveyard to the battlefield. they gain haste until end of turn.` | Also uncovered in: Commander Cube |


### Death Toll - Duskmourn: House of Horror Commander (28 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Arachnogenesis | `Create x <n>/<n> green spider creature tokens with reach, where x is the number of creatures attacking you. prevent all combat damage that would be dealt this turn by non-spider creatures.` |  |
| Carrion Grub | `~ gets +x/+<n>, where x is the greatest power among creature cards in your graveyard.` |  |
| Cemetery Tampering | `At the beginning of your upkeep, you may mill <n> cards. then if there are twenty or more cards in your graveyard, you may play the exiled card without paying its mana cost.` |  |
| Convert to Slime | Compound gap — `Destroy up to <n> target artifact, up to <n> target creature, and up to <n> target enchantment.`; `Then if there are <n> or more card types among cards in your graveyard, create an x/x green ooze creature token, where x is the total mana value of permanents destroyed this way.` |  |
| Crawling Sensation | `Whenever <n> or more land cards are put into your graveyard from anywhere for the first time each turn, create a <n>/<n> green insect creature token.` | Also uncovered in: Sultai Arisen - Tarkir: Dragonstorm Commander |
| Deadbridge Chant | `At the beginning of your upkeep, choose a card at random in your graveyard. if it's a creature card, put it onto the battlefield. otherwise, put it into your hand.` |  |
| Deluge of Doom | `All creatures get -x/-x until end of turn, where x is the number of card types among cards in your graveyard.` |  |
| Demolisher Spawn | `Whenever ~ attacks, if there are <n> or more card types among cards in your graveyard, other attacking creatures get +<n>/+<n> until end of turn.` | Also uncovered in: Commander Cube |
| Demonic Covenant | Compound gap — `At the beginning of your end step, create a <n>/<n> black demon creature token with flying, then mill <n> cards. if <n> cards that share all their card types were milled this way, sacrifice ~.`; `Whenever <n> or more demons you control attack a player, you draw a card and lose <n> life.` |  |
| Formless Genesis | `Create an x/x colorless shapeshifter creature token with changeling and deathtouch, where x is the number of land cards in your graveyard.` | Also uncovered in: World Shaper - Edge of Eternities Commander Deck |
| Grapple with the Past | `Mill <n> cards, then you may return a creature or land card from your graveyard to your hand.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Grist, the Hunger Tide | Compound gap — `+<n>: create a <n>/<n> black and green insect creature token, then mill a card. if an insect card was milled this way, put a loyalty counter on ~ and repeat this process.`; `As long as ~ isn't on the battlefield, it's a <n>/<n> insect creature in addition to its other types.`; `−<n>: each opponent loses life equal to the number of creature cards in your graveyard.` | Also uncovered in: Commander Cube |
| Into the Pit | `You may cast spells from the top of your library by sacrificing a nonland permanent in addition to paying their other costs.` |  |
| Ishkanah, Grafwidow | `<cost>: target opponent loses <n> life for each spider you control.` |  |
| Moldgraf Millipede | `When ~ enters, mill <n> cards, then put a +<n>/+<n> counter on ~ for each creature card in your graveyard.` |  |
| Moldgraf Monstrosity | `When ~ dies, exile it, then return <n> creature cards at random from your graveyard to the battlefield.` |  |
| Mulch | `Reveal the top <n> cards of your library. put all land cards revealed this way into your hand and the rest into your graveyard.` |  |
| Noxious Gearhulk | `When ~ enters, you may destroy another target creature. if a creature is destroyed this way, you gain life equal to its toughness.` | Also uncovered in: Commander Cube, Riveteer Rampage - New Capenna Commander, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Polluted Cistern // Dim Oubliette | `Whenever <n> or more cards are put into your graveyard from your library, each opponent loses <n> life for each card type among those cards.` |  |
| Rendmaw, Creaking Nest | `When ~ enters and whenever you play a card with <n> or more card types, each player creates a tapped <n>/<n> black bird creature token with flying. the tokens are goaded for the rest of the game.` |  |
| Scavenging Ooze | `<cost>: exile target card from a graveyard. if it was a creature card, put a +<n>/+<n> counter on ~ and you gain <n> life.` | Also uncovered in: Commander Cube, Kodama |
| Skola Grovedancer | `Whenever a land card is put into your graveyard from anywhere, you gain <n> life.` |  |
| Titania, Nature's Force | `You may play forests from your graveyard.` |  |
| Ursine Monstrosity | `At the beginning of combat on your turn, mill a card and choose an opponent at random. ~ attacks that player this combat if able. until end of turn, ~ gains indestructible and gets +<n>/+<n> for each card type among cards in your graveyard.` |  |
| Whip of Erebos | `<cost>, <cost>: return target creature card from your graveyard to the battlefield. it gains haste. exile it at the beginning of the next end step. if it would leave the battlefield, exile it instead of putting it anywhere else. activate only as a sorcery.` |  |
| Whispersilk Cloak | `Equipped creature can't be blocked and has shroud.` |  |
| Winter, Cynical Opportunist | `At the beginning of your end step, you may exile any number of cards from your graveyard with <n> or more card types among them. if you do, put a permanent card from among them onto the battlefield with a finality counter on it.` |  |
| Wrenn and Seven | Compound gap — `+<n>: reveal the top <n> cards of your library. put all land cards revealed this way into your hand and the rest into your graveyard.`; `<n>: put any number of land cards from your hand onto the battlefield tapped.`; `−<n>: create a green treefolk creature token with reach and ~`; `−<n>: return all permanent cards from your graveyard to your hand. you get an emblem with ~` |  |


### Endless Punishment - Duskmourn: House of Horror Commander (27 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Barbflare Gremlin | `Whenever a player taps a land for mana, if ~ is tapped, that player adds <n> mana of any type that land produced. then that land deals <n> damage to that player.` |  |
| Braids, Arisen Nightmare | `At the beginning of your end step, you may sacrifice an artifact, creature, enchantment, land, or planeswalker. if you do, each opponent may sacrifice a permanent of their choice that shares a card type with it. for each opponent who doesn't, that player loses <n> life and you draw a card.` | Also uncovered in: World Shaper - Edge of Eternities Commander Deck |
| Brash Taunter | `Whenever ~ is dealt damage, it deals that much damage to target opponent.` |  |
| Combustible Gearhulk | `When ~ enters, target opponent may have you draw <n> cards. if the player doesn't, you mill <n> cards, then ~ deals damage to that player equal to the total mana value of those cards.` | Also uncovered in: Living Energy - Aetherdrift Commander, Revival Trance - Final Fantasy Commander |
| Decree of Pain | `Destroy all creatures. they can't be regenerated. draw a card for each creature destroyed this way.` | Also uncovered in: Squirreled Away - Bloomburrow Commander |
| Enchanter's Bane | `At the beginning of your end step, target enchantment deals damage equal to its mana value to its controller unless that player sacrifices it.` |  |
| Fear of Burning Alive | `Whenever a source you control deals noncombat damage to an opponent, if there are <n> or more card types among cards in your graveyard, ~ deals that amount of damage to target creature that player controls.` |  |
| Florian, Voldaren Scion | `At the beginning of each of your postcombat main phases, look at the top x cards of your library, where x is the total amount of life your opponents lost this turn. exile <n> of those cards and put the rest on the bottom of your library in a random order. you may play the exiled card this turn.` |  |
| Grab the Prize | `Draw <n> cards. if the discarded card wasn't a land card, ~ deals <n> damage to each opponent.` |  |
| Kardur, Doomscourge | Compound gap — `When ~ enters, until your next turn, creatures your opponents control attack each combat if able and attack a player other than you if able.`; `Whenever an attacking creature dies, each opponent loses <n> life and you gain <n> life.` |  |
| Kederekt Parasite | `Whenever an opponent draws a card, if you control a red permanent, you may have ~ deal <n> damage to that player.` |  |
| Leechridden Swamp | `<cost>, <cost>: each opponent loses <n> life. activate only if you control <n> or more black permanents.` |  |
| Mask of Griselbrand | `Whenever equipped creature dies, you may pay x life, where x is its power. if you do, draw x cards.` |  |
| Massacre Girl | `When ~ enters, each other creature gets -<n>/-<n> until end of turn. whenever a creature dies this turn, each creature other than ~ gets -<n>/-<n> until end of turn.` |  |
| Mogis, God of Slaughter | `At the beginning of each opponent's upkeep, ~ deals <n> damage to that player unless they sacrifice a creature of their choice.` |  |
| Nightshade Harvester | `Whenever a land an opponent controls enters, that player loses <n> life. put a +<n>/+<n> counter on ~.` |  |
| Persistent Constrictor | `At the beginning of each opponent's upkeep, they lose <n> life and you put a -<n>/-<n> counter on up to <n> target creature they control.` |  |
| Rakdos, Lord of Riots | Compound gap — `Creature spells you cast cost <cost> less to cast for each <n> life your opponents have lost this turn.`; `You can't cast ~ unless an opponent lost life this turn.` |  |
| Sadistic Shell Game | `Starting with the next opponent in turn order, each player chooses a creature you don't control. destroy the chosen creatures.` |  |
| Spiked Corridor // Torture Pit | `When you unlock this door, create <n> <n>/<n> red devil creature tokens with ~` |  |
| Spinerock Knoll | `<cost>, <cost>: you may play the exiled card without paying its mana cost if an opponent was dealt <n> or more damage this turn.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Star Athlete | `Whenever ~ attacks, choose up to <n> target nonland permanent. its controller may sacrifice it. if they don't, ~ deals <n> damage to that player.` |  |
| Suspended Sentence | `Destroy target creature an opponent controls. that player loses <n> life. exile ~ with <n> time counters on it.` |  |
| The Lord of Pain | `Whenever a player casts their first spell each turn, choose another target player. ~ deals damage equal to that spell's mana value to the chosen player.` |  |
| Valgavoth, Harrower of Souls | `Whenever an opponent loses life for the first time during each of their turns, put a +<n>/+<n> counter on ~ and draw a card.` |  |
| Vial Smasher the Fierce | `Whenever you cast your first spell each turn, choose an opponent at random. vial smasher deals damage equal to that spell's mana value to that player or a planeswalker that player controls.` |  |
| Witch's Clinic | `<cost>, <cost>: target commander gains lifelink until end of turn.` |  |


### Eternal Might - Aetherdrift Commander (26 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Accursed Duneyard | `<cost>, <cost>: regenerate target shade, skeleton, specter, spirit, vampire, wraith, or zombie.` |  |
| Champion of Wits | `When ~ enters, you may draw cards equal to its power. if you do, discard <n> cards.` |  |
| Commence the Endgame | `Draw <n> cards, then amass zombies x, where x is the number of cards in your hand.` |  |
| Corpse Augur | `When ~ dies, you draw x cards and you lose x life, where x is the number of creature cards in target player's graveyard.` |  |
| Crowded Crypt | Compound gap — `<cost>, <cost>, sacrifice ~: create a <n>/<n> black zombie creature token with decayed for each corpse counter on ~.`; `Whenever a creature you control dies, put a corpse counter on ~.` |  |
| Dread Summons | `Each player mills x cards. for each creature card put into a graveyard this way, you create a tapped <n>/<n> black zombie creature token.` |  |
| Dreadhorde Invasion | `Whenever a zombie token you control with power <n> or greater attacks, it gains lifelink until end of turn.` |  |
| Forgotten Creation | `At the beginning of your upkeep, you may discard all the cards in your hand. if you do, draw that many cards.` |  |
| Gate to the Afterlife | `<cost>, <cost>, sacrifice ~: search your graveyard, hand, and/or library for a card named god-pharaoh's gift and put it onto the battlefield. if you search your library this way, shuffle. activate only if there are <n> or more creature cards in your graveyard.` |  |
| Gempalm Polluter | `When you cycle this card, you may have target player lose life equal to the number of zombies on the battlefield.` |  |
| Gravecrawler | `You may cast this card from your graveyard as long as you control a zombie.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Hashaton, Scarab's Fist | `Whenever you discard a creature card, you may pay <cost>. if you do, create a tapped token that's a copy of that card, except it's a <n>/<n> black zombie.` |  |
| Liliana, Death's Majesty | Compound gap — `−<n>: destroy all non-zombie creatures.`; `−<n>: return target creature card from your graveyard to the battlefield. that creature is a black zombie in addition to its other colors and types.` |  |
| Lord of the Accursed | `<cost>, <cost>: all zombies gain menace until end of turn.` |  |
| Lost Monarch of Ifnir | Compound gap — `At the beginning of your second main phase, if a player was dealt combat damage by a zombie this turn, mill <n> cards, then you may return a creature card from your graveyard to your hand.`; `Other zombies you control have afflict <n>.` |  |
| Maskwood Nexus | `Creatures you control are every creature type. the same is true for creature spells you control and creature cards you own that aren't on the battlefield.` | Also uncovered in: Squirreled Away - Bloomburrow Commander |
| On Wings of Gold | `Creatures you control that are zombies and/or tokens get +<n>/+<n> and have flying.` |  |
| Priest of the Crossing | `At the beginning of each end step, put x +<n>/+<n> counters on each creature you control, where x is the number of creatures that died under your control this turn.` |  |
| Prophet of the Scarab | `When ~ enters, draw cards equal to the number of zombies you control or the number of zombie cards in your graveyard, whichever is greater.` | Also uncovered in: Commander Cube |
| Renewed Solidarity | `At the beginning of your end step, for each token you control of the chosen type that entered this turn, create a token that's a copy of it.` |  |
| Rot Hulk | `When ~ enters, return up to x target zombie cards from your graveyard to the battlefield, where x is the number of opponents you have.` | Also uncovered in: Commander Cube |
| Temmet, Naktamun's Will | `Whenever you draw a card, zombies you control get +<n>/+<n> until end of turn.` | Also uncovered in: Commander Cube |
| The Scarab God | `At the beginning of your upkeep, each opponent loses x life and you scry x, where x is the number of zombies you control.` |  |
| Unholy Grotto | `<cost>, <cost>: put target zombie card from your graveyard on top of your library.` |  |
| Vizier of Many Faces | `You may have ~ enter as a copy of any creature on the battlefield, except if ~ was embalmed, the token has no mana cost, it's white, and it's a zombie in addition to its other types.` |  |
| Wizened Mentor | `Whenever an opponent activates an ability of a permanent that isn't a mana ability, you create a <n>/<n> white zombie creature token. this ability triggers only once each turn.` |  |


### Family Matters - Bloomburrow Commander (20 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aetherize | `Return all attacking creatures to their owner's hand.` |  |
| Bident of Thassa | `<cost>, <cost>: creatures your opponents control attack this turn if able.` |  |
| Boss's Chauffeur | `~ enters with a number of +<n>/+<n> counters on it equal to <n> plus the number of other creatures you control.` |  |
| Calamity of Cinders | `~ deals <n> damage to each untapped creature.` |  |
| Cut a Deal | `Each opponent draws a card, then you draw a card for each opponent who drew a card this way.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Devilish Valet | `Whenever another creature you control enters, double ~'s power until end of turn.` |  |
| Inferno Titan | `Whenever ~ enters or attacks, it deals <n> damage divided as you choose among <n>, <n>, or <n> targets.` | Also uncovered in: Riveteer Rampage - New Capenna Commander |
| Jacked Rabbit | `Whenever ~ attacks, create a number of <n>/<n> white rabbit creature tokens equal to ~'s power.` |  |
| Jazal Goldmane | `<cost>: attacking creatures you control get +x/+x until end of turn, where x is the number of attacking creatures.` |  |
| Junk Winder | `Whenever a token you control enters, tap target nonland permanent an opponent controls. it doesn't untap during its controller's next untap step.` |  |
| Murmuration | `At the beginning of your end step, for each spell you've cast this turn, create a <n>/<n> blue bird creature token with flying named storm crow.` |  |
| Pollywog Prodigy | `Whenever an opponent casts a noncreature spell with mana value less than ~'s power, draw a card.` |  |
| Rapid Augmenter | Compound gap — `Whenever another creature you control enters, if it wasn't cast, put a +<n>/+<n> counter on ~ and ~ can't be blocked this turn.`; `Whenever another creature you control with base power <n> enters, it gains haste until end of turn.` |  |
| Rose Room Treasurer | `Whenever another creature you control enters, create a treasure token if this is the first or second time this ability has resolved this turn. otherwise, you may pay <cost>. when you do, ~ deals x damage to any target.` |  |
| Shield Broker | `When ~ enters, put a shield counter on target noncommander creature you don't control. you gain control of that creature for as long as it has a shield counter on it.` |  |
| Stolen by the Fae | `Return target creature with mana value x to its owner's hand. you create x <n>/<n> blue faerie creature tokens with flying.` |  |
| Storm of Souls | `Return all creature cards from your graveyard to the battlefield. each of them is a <n>/<n> spirit with flying in addition to its other types. exile ~.` |  |
| Tetsuko Umezawa, Fugitive | `Creatures you control with power or toughness <n> or less can't be blocked.` |  |
| Time Wipe | `Return a creature you control to its owner's hand, then destroy all creatures.` | Also uncovered in: Jeskai Striker - Tarkir: Dragonstorm Commander, Miracle Worker - Duskmourn: House of Horror Commander |
| Zinnia, Valley's Voice | Compound gap — `~ gets +x/+<n>, where x is the number of other creatures you control with base power <n>.`; `Creature spells you cast gain offspring <cost> as you cast them.` |  |


### Goblins (10 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Coat of Arms | `Each creature gets +<n>/+<n> for each other creature on the battlefield that shares at least <n> creature type with it.` |  |
| Foundry Street Denizen | `Whenever another red creature you control enters, ~ gets +<n>/+<n> until end of turn.` |  |
| Goblin Matron | `When ~ enters, you may search your library for a goblin card, reveal that card, put it into your hand, then shuffle.` |  |
| Krenko, Tin Street Kingpin | `Whenever ~ attacks, put a +<n>/+<n> counter on it, then create a number of <n>/<n> red goblin creature tokens equal to ~'s power.` |  |
| Legion Loyalist | `Whenever ~ and at least <n> other creatures attack, creatures you control gain first strike and trample until end of turn and can't be blocked by creature tokens this turn.` |  |
| Muxus, Goblin Grandee | Compound gap — `When ~ enters, reveal the top <n> cards of your library. put all goblin creature cards with mana value <n> or less from among them onto the battlefield and the rest on the bottom of your library in a random order.`; `Whenever ~ attacks, it gets +<n>/+<n> until end of turn for each other goblin you control.` |  |
| Reckless Bushwhacker | `When ~ enters, if its surge cost was paid, other creatures you control get +<n>/+<n> and gain haste until end of turn.` |  |
| Shared Animosity | `Whenever a creature you control attacks, it gets +<n>/+<n> until end of turn for each other attacking creature that shares a creature type with it.` |  |
| Thornbite Staff | `Whenever a shaman creature enters, you may attach ~ to it.` |  |
| Wort, Boggart Auntie | `At the beginning of your upkeep, you may return target goblin card from your graveyard to your hand.` |  |


### Hope to the last (26 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Ajani, Strength of the Pride | Compound gap — `+<n>: you gain life equal to the number of creatures you control plus the number of planeswalkers you control.`; `<n>: if you have at least <n> life more than your starting life total, exile ~ and each artifact and creature your opponents control.`; `−<n>: create a <n>/<n> white cat soldier creature token named ~'s pridemate with ~` |  |
| Angel of Destiny | Compound gap — `At the beginning of your end step, if you have at least <n> life more than your starting life total, each player ~ attacked this turn loses the game.`; `Whenever a creature you control deals combat damage to a player, you and that player each gain that much life.` |  |
| Beacon of Immortality | `Double target player's life total. shuffle ~ into its owner's library.` |  |
| Exemplar of Light | `Whenever you put <n> or more +<n>/+<n> counters on ~, draw a card. this ability triggers only once each turn.` | Also uncovered in: Commander Cube |
| Gogo, Master of Mimicry | `<cost>, <cost>: copy target activated or triggered ability you control x times. you may choose new targets for the copies. this ability can't be copied and x can't be <n>.` | Also uncovered in: SpongeBob and the legendary Burger |
| Gold-Forged Thopteryx | `Each legendary permanent you control has ward <cost>.` |  |
| Haliya, Guided by Light | `At the beginning of your end step, draw a card if you've gained <n> or more life this turn.` | Also uncovered in: Commander Cube |
| Honor the Fallen | `Exile all creature cards from all graveyards. you gain <n> life for each card exiled this way.` |  |
| Hope Estheim | `At the beginning of your end step, each opponent mills x cards, where x is the amount of life you gained this turn.` |  |
| Memory Erosion | `Whenever an opponent casts a spell, that player mills <n> cards.` |  |
| Minas Tirith | `<cost>, <cost>: draw a card. activate only if you attacked with <n> or more creatures this turn.` | Also uncovered in: Commander Cube |
| Monumental Henge | `<cost>, <cost>: look at the top <n> cards of your library. you may reveal a historic card from among them and put it into your hand. put the rest on the bottom of your library in a random order.` |  |
| Nykthos Paragon | `Whenever you gain life, you may put that many +<n>/+<n> counters on each creature you control. do this only once each turn.` | Also uncovered in: Commander Cube |
| Profane Memento | `Whenever a creature card is put into an opponent's graveyard from anywhere, you gain <n> life.` |  |
| Psychic Corrosion | `Whenever you draw a card, each opponent mills <n> cards.` |  |
| Resplendent Angel | `<cost>: until end of turn, ~ gets +<n>/+<n> and gains lifelink.` | Also uncovered in: Commander Cube |
| Restoration Magic | Compound gap — `• cura — <cost> — target permanent gains hexproof and indestructible until end of turn. you gain <n> life.`; `• curaga — <cost> — permanents you control gain hexproof and indestructible until end of turn. you gain <n> life.`; `• cure — <cost> — target permanent gains hexproof and indestructible until end of turn.` |  |
| Rivendell | `<cost>, <cost>: scry <n>. activate only if you control a legendary creature.` | Also uncovered in: Commander Cube |
| Riverchurn Monument | Compound gap — `<cost>, <cost>: any number of target players each mill <n> cards.`; `Exhaust — <cost>, <cost>: any number of target players each mill cards equal to the number of cards in their graveyard.` |  |
| Shabraz, the Skyshark | `<cost>: target human gains flying until end of turn.` |  |
| Speaker of the Heavens | `<cost>: create a <n>/<n> white angel creature token with flying. activate only if you have at least <n> life more than your starting life total and only as a sorcery.` |  |
| Sphinx of the Revelation | `Whenever you gain life, you get that many <cost>.` |  |
| Starfield Shepherd | `When ~ enters, search your library for a basic plains card or a creature card with mana value <n> or less, reveal it, put it into your hand, then shuffle.` |  |
| The Water Crystal | Compound gap — `<cost>, <cost>: each opponent mills cards equal to the number of cards in your hand.`; `If an opponent would mill <n> or more cards, they mill that many cards plus <n> instead.` |  |
| Well of Lost Dreams | `Whenever you gain life, you may pay <cost>, where x is less than or equal to the amount of life you gained. if you do, draw x cards.` |  |
| Will, Scion of Peace | `<cost>: spells you cast this turn that are white and/or blue cost <cost> less to cast, where x is the amount of life you gained this turn. activate only as a sorcery.` |  |


### Hydranten (15 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Genesis Hydra | `When you cast this spell, reveal the top x cards of your library. you may put a nonland permanent card with mana value x or less from among them onto the battlefield. then shuffle the rest into your library.` | Also uncovered in: Raggadragga, Goreguts Boss |
| Geometer's Arthropod | `Whenever you cast a spell with <cost> in its mana cost, look at the top x cards of your library. put <n> of them into your hand and the rest on the bottom of your library in a random order.` |  |
| Herald of Secret Streams | `Creatures you control with +<n>/+<n> counters on them can't be blocked.` | Also uncovered in: Commander Cube |
| Kindred Discovery | `Whenever a creature you control of the chosen type enters or attacks, draw a card.` |  |
| Kodama of the West Tree | `Whenever a modified creature you control deals combat damage to a player, search your library for a basic land card, put it onto the battlefield tapped, then shuffle.` | Also uncovered in: Kodama |
| Mana Reflection | `If you tap a permanent for mana, it produces twice as much of that mana instead.` |  |
| Mathemagics | `Target player draws <n>ˣ cards.` |  |
| Mind into Matter | `Draw x cards. then you may put a permanent card with mana value x or less from your hand onto the battlefield tapped.` |  |
| Neverwinter Hydra | `As ~ enters, roll x d<n>. it enters with a number of +<n>/+<n> counters on it equal to the total of those results.` |  |
| Paradox Surveyor | `When ~ enters, look at the top <n> cards of your library. you may reveal a land card or a card with <cost> in its mana cost from among them and put it into your hand. put the rest on the bottom of your library in a random order.` |  |
| Power Sink | `Counter target spell unless its controller pays <cost>. if that player doesn't, they tap all lands with mana abilities they control and lose all unspent mana.` |  |
| Primal Vigor | Compound gap — `If <n> or more +<n>/+<n> counters would be put on a creature, twice that many +<n>/+<n> counters are put on that creature instead.`; `If <n> or more tokens would be created, twice that many of those tokens are created instead.` |  |
| Runadi, Behemoth Caller | Compound gap — `Creatures you control with <n> or more +<n>/+<n> counters on them have haste.`; `Whenever you cast a creature spell with mana value <n> or greater, that creature enters with x additional +<n>/+<n> counters on it, where x is its mana value minus <n>.` |  |
| Simic Ascendancy | Compound gap — `At the beginning of your upkeep, if ~ has twenty or more growth counters on it, you win the game.`; `Whenever <n> or more +<n>/+<n> counters are put on a creature you control, put that many growth counters on ~.` | Also uncovered in: Peace Offering - Bloomburrow Commander |
| Zaxara, the Exemplary | `Whenever you cast a spell with <cost> in its mana cost, create a <n>/<n> green hydra creature token, then put x +<n>/+<n> counters on it.` |  |


### Jeskai Striker - Tarkir: Dragonstorm Commander (15 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Adaptive Training Post | Compound gap — `Remove <n> charge counters from ~: when you next cast an instant or sorcery spell this turn, copy it and you may choose new targets for the copy.`; `Whenever you cast an instant or sorcery spell, if ~ has fewer than <n> charge counters on it, put a charge counter on it.` |  |
| Aligned Heart | `Whenever you cast your second spell each turn, put a rally counter on ~. then create a <n>/<n> white monk creature token with prowess for each rally counter on it.` |  |
| Baral and Kari Zev | `Whenever you cast your first instant or sorcery spell each turn, you may cast a spell with lesser mana value that shares a card type with it from your hand without paying its mana cost. if you don't, create first mate ragavan, a legendary <n>/<n> red monkey pirate creature token. it gains haste until end of turn.` |  |
| Baral's Expertise | `Return up to <n> target artifacts and/or creatures to their owners' hands.` | Also uncovered in: Commander Cube |
| Compulsive Research | `Target player draws <n> cards. then that player discards <n> cards unless they discard a land card.` |  |
| Curse of Opulence | `Whenever enchanted player is attacked, create a gold token. each opponent attacking that player does the same.` |  |
| Expansion // Explosion | `Copy target instant or sorcery spell with mana value <n> or less. you may choose new targets for the copy.` |  |
| Frantic Search | `Draw <n> cards, then discard <n> cards. untap up to <n> lands.` | Also uncovered in: Commander Cube, Oops! All Night's Whispers |
| Shiko and Narset, Unified | `Whenever you cast your second spell each turn, copy that spell if it targets a permanent or player, and you may choose new targets for the copy. if you don't copy a spell this way, draw a card.` |  |
| Tempest Technique | `Enchanted creature gets +<n>/+<n> for each enchantment you control.` |  |
| Transcendent Dragon | `When ~ enters, if you cast it, counter target spell. if that spell is countered this way, exile it instead of putting it into its owner's graveyard, then you may cast it without paying its mana cost.` |  |
| Transforming Flourish | `Destroy target artifact or creature you don't control. if that permanent is destroyed this way, its controller exiles cards from the top of their library until they exile a nonland card, then they may cast that card without paying its mana cost.` |  |
| Vanquish the Horde | `This spell costs <cost> less to cast for each creature on the battlefield.` | Also uncovered in: Limit Break - Final Fantasy Commander, Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck |
| Velomachus Lorehold | `Whenever ~ attacks, look at the top <n> cards of your library. you may cast an instant or sorcery spell with mana value less than or equal to ~'s power from among them without paying its mana cost. put the rest on the bottom of your library in a random order.` |  |
| Voracious Bibliophile | `Whenever you cast a spell with <n> or more targets, draw that many cards.` |  |


### Jump Scare! - Duskmourn: House of Horror Commander (28 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Arixmethes, Slumbering Isle | Compound gap — `~ enters tapped with <n> slumber counters on it.`; `As long as ~ has a slumber counter on it, it's a land.`; `Whenever you cast a spell, you may remove a slumber counter from ~.` |  |
| Augur of Autumn | `As long as you control <n> or more creatures with different powers, you may cast creature spells from the top of your library.` | Also uncovered in: World Shaper - Edge of Eternities Commander Deck |
| Curator Beastie | `Colorless creatures you control enter with <n> additional +<n>/+<n> counters on them.` |  |
| Deathmist Raptor | `Whenever a permanent you control is turned face up, you may return this card from your graveyard to the battlefield face up or face down.` |  |
| Disorienting Choice | `For each opponent, choose up to <n> target artifact or enchantment that player controls. for each permanent chosen this way, its controller may exile it. then if <n> or more of the chosen permanents are still on the battlefield, you search your library for up to that many land cards, put them onto the battlefield tapped, then shuffle.` |  |
| Experimental Lab // Staff Room | `When you unlock this door, manifest dread, then put <n> +<n>/+<n> counters and a trample counter on that creature.` |  |
| Ezuri's Predation | `For each creature your opponents control, create a <n>/<n> green phyrexian beast creature token. each of those tokens fights a different <n> of those creatures.` |  |
| Giggling Skitterspike | `Whenever ~ attacks, blocks, or becomes the target of a spell, it deals damage equal to its power to each opponent.` | Also uncovered in: Wick Snail Boom |
| Glitch Interpreter | Compound gap — `When ~ enters, if you control no face-down permanents, return ~ to its owner's hand and manifest dread.`; `Whenever <n> or more colorless creatures you control deal combat damage to a player, draw a card.` |  |
| Growing Dread | `Whenever you turn a permanent face up, put a +<n>/+<n> counter on it.` |  |
| Kheru Spellsnatcher | `When ~ is turned face up, counter target spell. if that spell is countered this way, exile it instead of putting it into its owner's graveyard. you may cast that card without paying its mana cost for as long as it remains exiled.` |  |
| Kianne, Corrupted Memory | Compound gap — `As long as ~'s power is even, you may cast noncreature spells as though they had flash.`; `As long as ~'s power is odd, you may cast creature spells as though they had flash.` |  |
| Multani, Yavimaya's Avatar | `~ gets +<n>/+<n> for each land you control and each land card in your graveyard.` | Also uncovered in: Sultai Arisen - Tarkir: Dragonstorm Commander, World Shaper - Edge of Eternities Commander Deck |
| Overwhelming Stampede | `Creatures you control gain trample and get +x/+x, where x is the greatest power among creatures you control until end of turn.` |  |
| Primordial Mist | `Exile a face-down permanent you control face up: you may play that card this turn.` |  |
| Rashmi, Eternities Crafter | `Whenever you cast your first spell each turn, reveal the top card of your library. you may cast it without paying its mana cost if it's a spell with lesser mana value. if you don't cast it, put it into your hand.` |  |
| Sandwurm Convergence | `Creatures with flying can't attack you or planeswalkers you control.` |  |
| Scroll of Fate | `<cost>: manifest a card from your hand.` |  |
| Scute Swarm | `Whenever a land you control enters, create a <n>/<n> green insect creature token. if you control <n> or more lands, create a token that's a copy of ~ instead.` | Also uncovered in: Kodama |
| Shigeki, Jukai Visionary | Compound gap — `<cost>, <cost>, return ~ to its owner's hand: reveal the top <n> cards of your library. you may put a land card from among them onto the battlefield tapped. put the rest into your graveyard.`; `<cost>, discard this card: return x target nonlegendary cards from your graveyard to your hand.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Shriekwood Devourer | `Whenever you attack with <n> or more creatures, untap up to x lands, where x is the greatest power among those creatures.` |  |
| Temur War Shaman | `Whenever a permanent you control is turned face up, if it's a creature, you may have it fight target creature you don't control.` |  |
| Thunderfoot Baloth | `As long as you control your commander, ~ gets +<n>/+<n> and other creatures you control get +<n>/+<n> and have trample.` |  |
| Trail of Mystery | Compound gap — `Whenever a face-down creature you control enters, you may search your library for a basic land card, reveal it, put it into your hand, then shuffle.`; `Whenever a permanent you control is turned face up, if it's a creature, it gets +<n>/+<n> until end of turn.` |  |
| Trygon Predator | `Whenever ~ deals combat damage to a player, you may destroy target artifact or enchantment that player controls.` |  |
| Whisperwood Elemental | `Sacrifice ~: until end of turn, face-up nontoken creatures you control gain ~` |  |
| Yedora, Grave Gardener | `Whenever another nontoken creature you control dies, you may return it to the battlefield face down under its owner's control. it's a forest land.` |  |
| Zimone, Mystery Unraveler | `Whenever a land you control enters, manifest dread if this is the first time this ability has resolved this turn. otherwise, you may turn a permanent you control face up.` |  |


### Kodama (23 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Amulet of Vigor | `Whenever a permanent you control enters tapped, untap it.` |  |
| Ancient Animus | `Put a +<n>/+<n> counter on target creature you control if it's legendary. then it fights target creature an opponent controls.` |  |
| Armorcraft Judge | `When ~ enters, draw a card for each creature you control with a +<n>/+<n> counter on it.` | Also uncovered in: Commander Cube |
| Bonders' Enclave | `<cost>, <cost>: draw a card. activate only if you control a creature with power <n> or greater.` | Also uncovered in: Commander Cube, Limit Break - Final Fantasy Commander |
| Chocobo Racetrack | `Whenever a land you control enters, create a <n>/<n> green bird creature token with ~` |  |
| Court of Garenbrig | `At the beginning of your upkeep, distribute <n> +<n>/+<n> counters among up to <n> target creatures. then if you're the monarch, double the number of +<n>/+<n> counters on each creature you control.` |  |
| Defiler of Vigor | Compound gap — `As an additional cost to cast green permanent spells, you may pay <n> life. those spells cost <cost> less to cast if you paid life this way. this effect reduces only the amount of green mana you pay.`; `Whenever you cast a green permanent spell, put a +<n>/+<n> counter on each creature you control.` |  |
| Evolution Witness | `Whenever <n> or more +<n>/+<n> counters are put on ~, return target permanent card from your graveyard to your hand.` |  |
| Innkeeper's Talent | `Permanents you control with counters on them have ward <cost>.` | Also uncovered in: Commander Cube |
| Nissa, Ascended Animist | Compound gap — `+<n>: create an x/x green phyrexian horror creature token, where x is ~'s loyalty.`; `−<n>: until end of turn, creatures you control get +<n>/+<n> for each forest you control and gain trample.` |  |
| Nissa, Vital Force | `+<n>: untap target land you control. until your next turn, it becomes a <n>/<n> elemental creature with haste. it's still a land.` |  |
| Nissa, Who Shakes the World | Compound gap — `+<n>: put <n> +<n>/+<n> counters on up to <n> target noncreature land you control. untap it. it becomes a <n>/<n> elemental creature with vigilance and haste that's still a land.`; `Whenever you tap a forest for mana, add an additional <cost>.`; `−<n>: you get an emblem with ~ search your library for any number of forest cards, put them onto the battlefield tapped, then shuffle.` |  |
| Pathbreaker Ibex | `Whenever ~ attacks, creatures you control gain trample and get +x/+x until end of turn, where x is the greatest power among creatures you control.` |  |
| Railway Brawler | `Whenever another creature you control enters, put x +<n>/+<n> counters on it, where x is its power.` | Also uncovered in: Commander Cube |
| Ram Through | `Target creature you control deals damage equal to its power to target creature you don't control. if the creature you control has trample, excess damage is dealt to that creature's controller instead.` |  |
| Ride the Shoopuf | `<cost>: ~ becomes a <n>/<n> beast creature in addition to its other types.` |  |
| Roaring Earth | Compound gap — `<cost>, discard this card: put x +<n>/+<n> counters on target land you control. it becomes a <n>/<n> green spirit creature with haste. it's still a land.`; `Whenever a land you control enters, put a +<n>/+<n> counter on target creature or vehicle you control.` |  |
| Sapling Nursery | `<cost>, exile ~: treefolk and forests you control gain indestructible until end of turn.` |  |
| Springheart Nantuko | `Whenever a land you control enters, you may pay <cost> if ~ is attached to a creature you control. if you do, create a token that's a copy of that creature. if you didn't create a token this way, create a <n>/<n> green insect creature token.` |  |
| Summoning Materia | `As long as ~ is attached to a creature, you may cast creature spells from the top of your library.` | Also uncovered in: Limit Break - Final Fantasy Commander |
| Titanic Brawl | `This spell costs <cost> less to cast if it targets a creature you control with a +<n>/+<n> counter on it.` |  |
| Traveling Chocobo | Compound gap — `If a land or bird you control entering the battlefield causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.`; `You may play lands and cast bird spells from the top of your library.` |  |
| Tribute to the World Tree | `Whenever a creature you control enters, draw a card if its power is <n> or greater. otherwise, put <n> +<n>/+<n> counters on it.` |  |


### Limit Break - Final Fantasy Commander (34 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aerith, Last Ancient | `At the beginning of your end step, if you gained life this turn, return target creature card from your graveyard to your hand. if you gained <n> or more life this turn, return that card to the battlefield instead.` | Also uncovered in: SpongeBob and the legendary Burger |
| Armory Automaton | `Whenever ~ enters or attacks, you may attach any number of target equipment to it.` |  |
| Avalanche of Sector 7 | Compound gap — `~'s power is equal to the number of artifacts your opponents control.`; `Whenever an opponent activates an ability of an artifact they control, ~ deals <n> damage to that player.` |  |
| Barret Wallace | `Whenever ~ attacks, it deals damage equal to the number of equipped creatures you control to defending player.` |  |
| Barret, Avalanche Leader | `At the beginning of combat on your turn, attach up to <n> target equipment you control to target rebel you control.` |  |
| Cait Sith, Fortune Teller | `At the beginning of combat on your turn, scry <n>, then exile the top card of your library. you may play that card this turn. when you exile a card this way, target creature you control gets +x/+<n> until end of turn, where x is that card's mana value.` |  |
| Champion's Helm | `As long as equipped creature is legendary, it has hexproof.` |  |
| Cid, Freeflier Pilot | Compound gap — `<cost>, <cost>: return target equipment or vehicle card from your graveyard to your hand.`; `Equipment and vehicle spells you cast cost <cost> less to cast.` |  |
| Clever Concealment | `Any number of target nonland permanents you control phase out.` |  |
| Cloud's Limit Break | Compound gap — `• blade beam — <cost> — destroy any number of target tapped creatures with different controllers.`; `• cross-slash — <cost> — destroy target tapped creature.`; `• omnislash — <cost> — destroy all tapped creatures.` |  |
| Cloud, Ex-SOLDIER | Compound gap — `When ~ enters, attach up to <n> target equipment you control to it.`; `Whenever ~ attacks, draw a card for each equipped attacking creature you control. then if ~ has power <n> or greater, create <n> treasure tokens.` |  |
| Elena, Turk Recruit | `When ~ enters, return target non-assassin historic card from your graveyard to your hand.` |  |
| Furious Rise | `At the beginning of your end step, if you control a creature with power <n> or greater, exile the top card of your library. you may play that card until you exile another card with ~.` |  |
| Heidegger, Shinra Executive | Compound gap — `At the beginning of combat on your turn, target creature you control gets +x/+<n> until end of turn, where x is the number of soldiers you control.`; `At the beginning of your end step, create a number of <n>/<n> white soldier creature tokens equal to the number of opponents who control more creatures than you.` |  |
| Hellkite Tyrant | Compound gap — `At the beginning of your upkeep, if you control twenty or more artifacts, you win the game.`; `Whenever ~ deals combat damage to a player, gain control of all artifacts that player controls.` |  |
| Hero's Blade | `Whenever a legendary creature you control enters, you may attach ~ to it.` |  |
| Hero's Heirloom | `As long as equipped creature is legendary, it has trample and haste.` |  |
| Inspiring Statuary | `Nonartifact spells you cast have improvise.` |  |
| Lifestream's Blessing | `Draw x cards, where x is the greatest power among creatures you controlled as you cast this spell. if this spell was cast from exile, you gain twice x life.` |  |
| Mask of Memory | `Whenever equipped creature deals combat damage to a player, you may draw <n> cards. if you do, discard a card.` |  |
| Professor Hojo | Compound gap — `The first activated ability you activate during your turn that targets a creature you control costs <cost> less to activate.`; `Whenever <n> or more creatures you control become the target of an activated ability, draw a card. this ability triggers only once each turn.` |  |
| Puresteel Paladin | `Equipment you control have equip <cost> as long as you control <n> or more artifacts.` |  |
| Red XIII, Proud Warrior | `When ~ enters, return target aura or equipment card from your graveyard to your hand.` |  |
| SOLDIER Military Program | Compound gap — `At the beginning of combat on your turn, choose <n>. if you control a commander, you may choose both instead.`; `• create a <n>/<n> white soldier creature token.`; `• put a +<n>/+<n> counter on each of up to <n> soldiers you control.` |  |
| Scavenger Grounds | `<cost>, <cost>, sacrifice a desert: exile all graveyards.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Sephiroth, Fallen Hero | `Whenever ~ attacks, you may put a cell counter on target creature. until end of turn, each modified creature you control has base power and toughness <n>/<n>.` |  |
| Summon: Kujata | Compound gap — `I — lightning — ~ deals <n> damage to each of up to <n> target creatures.`; `Ii — ice — up to <n> target creatures can't block this turn.`; `Iii — fire — discard a card, then draw <n> cards. when you discard a card this way, ~ deals damage equal to that card's mana value to each opponent.` |  |
| Ultimate Magic: Holy | `Permanents you control gain indestructible until end of turn. if this spell was cast from exile, prevent all damage that would be dealt to you this turn.` |  |
| Ultimate Magic: Meteor | `~ deals <n> damage to each creature. if this spell was cast from exile, for each opponent, choose an artifact or land that player controls. destroy the chosen permanents.` |  |
| Unfinished Business | `Return target creature card from your graveyard to the battlefield, then return up to <n> target aura and/or equipment cards from your graveyard to the battlefield attached to that creature.` |  |
| Vincent, Vengeful Atoner | `Whenever ~ deals combat damage to an opponent, it deals that much damage to each other opponent if ~'s power is <n> or greater.` |  |
| Wrecking Ball Arm | `Equipped creature has base power and toughness <n>/<n> and can't be blocked by creatures with power <n> or less.` |  |
| Yuffie, Materia Hunter | `When ~ enters, gain control of target noncreature artifact for as long as you control ~. then you may attach an equipment you control to ~.` |  |
| Zack Fair | `<cost>, sacrifice ~: target creature you control gains indestructible until end of turn. put ~'s counters on that creature and attach an equipment that was attached to ~ to that creature.` |  |


### Living Energy - Aetherdrift Commander (24 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Academy Ruins | `<cost>, <cost>: put target artifact card from your graveyard on top of your library.` |  |
| Adaptive Omnitool | `Whenever equipped creature attacks, look at the top <n> cards of your library. you may reveal an artifact card from among them and put it into your hand. put the rest on the bottom of your library in a random order.` |  |
| Aetherflux Conduit | Compound gap — `<cost>, pay fifty <cost>: draw <n> cards. you may cast any number of spells from your hand without paying their mana costs.`; `Whenever you cast a spell, you get an amount of <cost> equal to the amount of mana spent to cast that spell.` |  |
| Aetheric Amplifier | Compound gap — `<cost>, <cost>: choose <n>. activate only as a sorcery.`; `• double the number of each kind of counter on target permanent.`; `• double the number of each kind of counter you have.` |  |
| Aethersquall Ancient | `Pay <n> <cost>: return all other creatures to their owners' hands. activate only as a sorcery.` |  |
| Aethertide Whale | `When ~ enters, you get <n> <cost>.` |  |
| Aetherworks Marvel | Compound gap — `<cost>, pay <n> <cost>: look at the top <n> cards of your library. you may cast a spell from among them without paying its mana cost. put the rest on the bottom of your library in a random order.`; `Whenever a permanent you control is put into a graveyard, you get <cost>.` |  |
| Bespoke Battlewagon | `Pay <cost>: ~ becomes an artifact creature until end of turn.` |  |
| Confiscation Coup | `Choose target artifact or creature. you get <cost>, then you may pay an amount of <cost> equal to that permanent's mana value. if you do, gain control of it.` |  |
| Druid of Purification | `When ~ enters, starting with you, each player may choose an artifact or enchantment you don't control. destroy each permanent chosen this way.` | Also uncovered in: Commander Cube |
| Lightning Runner | `Whenever ~ attacks, you get <cost>, then you may pay <n> <cost>. if you pay, untap all creatures you control, and after this phase, there is an additional combat phase.` |  |
| Loyal Apprentice | `At the beginning of combat on your turn, if you control your commander, create a <n>/<n> colorless thopter artifact creature token with flying. that token gains haste until end of turn.` | Also uncovered in: Commander Cube, Mardu Surge - Tarkir: Dragonstorm Commander |
| Midnight Clock | `When the twelfth hour counter is put on ~, shuffle your hand and graveyard into your library, then draw <n> cards. exile ~.` |  |
| Nissa, Worldsoul Speaker | `You may pay <n> <cost> rather than pay the mana cost for permanent spells you cast.` |  |
| One with the Machine | `Draw cards equal to the greatest mana value among artifacts you control.` |  |
| Panharmonicon | `If an artifact or creature entering causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.` |  |
| Peema Aether-Seer | Compound gap — `Pay <cost>: target creature blocks this turn if able.`; `When ~ enters, you get an amount of <cost> equal to the greatest power among creatures you control.` |  |
| Rampaging Aetherhood | `At the beginning of your upkeep, you get an amount of <cost> equal to ~'s power. then you may pay <n> or more <cost>. if you do, put that many +<n>/+<n> counters on ~.` |  |
| Saheeli, Radiant Creator | Compound gap — `At the beginning of combat on your turn, you may pay <cost>. when you do, create a token that's a copy of target permanent you control, except it's a <n>/<n> artifact creature in addition to its other types and has haste. sacrifice it at the beginning of the next end step.`; `Whenever you cast an artificer or artifact spell, you get <cost>.` |  |
| Saheeli, Sublime Artificer | `−<n>: target artifact you control becomes a copy of another target artifact or creature you control until end of turn, except it's an artifact in addition to its other types.` |  |
| Stridehangar Automaton | `If <n> or more artifact tokens would be created under your control, those tokens plus an additional <n>/<n> colorless thopter artifact creature token with flying are created instead.` |  |
| Territorial Aetherkite | `When ~ enters, you get <cost>. then you may pay <n> or more <cost>. when you do, ~ deals that much damage to each other creature.` |  |
| Thopter Spy Network | `Whenever <n> or more artifact creatures you control deal combat damage to a player, draw a card.` | Also uncovered in: Shorikai Vehicles |
| Triplicate Titan | `When ~ dies, create a <n>/<n> colorless golem artifact creature token with flying, a <n>/<n> colorless golem artifact creature token with vigilance, and a <n>/<n> colorless golem artifact creature token with trample.` |  |


### Mardu Surge - Tarkir: Dragonstorm Commander (26 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bitter Triumph | `As an additional cost to cast this spell, discard a card or pay <n> life.` | Also uncovered in: Commander Cube, Oops! All Night's Whispers |
| Bone Devourer | Compound gap — `~ enters with a number of +<n>/+<n> counters on it equal to the number of creatures that died this turn.`; `When ~ dies, you draw x cards and you lose x life, where x is the number of +<n>/+<n> counters on it.` |  |
| Chittering Witch | `When ~ enters, create a number of <n>/<n> black rat creature tokens equal to the number of opponents you have.` | Also uncovered in: Squirreled Away - Bloomburrow Commander |
| Commander's Insignia | `Creatures you control get +<n>/+<n> for each time you've cast your commander from the command zone this game.` |  |
| Divine Visitation | `If <n> or more creature tokens would be created under your control, that many <n>/<n> white angel creature tokens with flying and vigilance are created instead.` |  |
| Eliminate the Competition | Compound gap — `As an additional cost to cast this spell, sacrifice x creatures.`; `Destroy x target creatures.` |  |
| Gix, Yawgmoth Praetor | Compound gap — `<cost>, discard x cards: exile the top x cards of target opponent's library. you may play lands and cast spells from among cards exiled this way without paying their mana costs.`; `Whenever a creature deals combat damage to <n> of your opponents, its controller may pay <n> life. if they do, they draw a card.` |  |
| Grand Crescendo | `Create x <n>/<n> green and white citizen creature tokens. creatures you control gain indestructible until end of turn.` |  |
| Grenzo, Havoc Raiser | Compound gap — `Whenever a creature you control deals combat damage to a player, choose <n> —`; `• exile the top card of that player's library. until end of turn, you may cast that card and you may spend mana as though it were mana of any color to cast that spell.`; `• goad target creature that player controls.` |  |
| Hour of Reckoning | `Destroy all nontoken creatures.` |  |
| Idol of Oblivion | `<cost>: draw a card. activate only if you created a token this turn.` | Also uncovered in: Commander Cube, Squirreled Away - Bloomburrow Commander |
| Infantry Shield | `Equipped creature has menace and mobilize x, where x is its power.` |  |
| Ironwill Forger | `At the beginning of combat on your turn, if you control your commander, target nonlegendary creature you control gains myriad until end of turn.` |  |
| Kaya, Geist Hunter | Compound gap — `+<n>: creatures you control gain deathtouch until end of turn. put a +<n>/+<n> counter on up to <n> target creature token you control.`; `−<n>: exile all cards from all graveyards, then create a <n>/<n> white spirit creature token with flying for each card exiled this way.`; `−<n>: until end of turn, if <n> or more tokens would be created under your control, twice that many of those tokens are created instead.` |  |
| Legion Warboss | `At the beginning of combat on your turn, create a <n>/<n> red goblin creature token. that token gains haste until end of turn and attacks this combat if able.` |  |
| Mindblade Render | `Whenever your opponents are dealt combat damage, if any of that damage was dealt by a warrior, you draw a card and you lose <n> life.` |  |
| Myr Battlesphere | `Whenever ~ attacks, you may tap x untapped myr you control. if you do, ~ gets +x/+<n> until end of turn and deals x damage to the player or planeswalker it's attacking.` |  |
| Neriv, Crackling Vanguard | `Whenever ~ attacks, exile a number of cards from the top of your library equal to the number of differently named tokens you control. during any turn you attacked with a commander, you may play those cards.` |  |
| Ogre Battledriver | `Whenever another creature you control enters, that creature gets +<n>/+<n> and gains haste until end of turn.` |  |
| Stroke of Midnight | `Destroy target nonland permanent. its controller creates a <n>/<n> white human creature token.` | Also uncovered in: Commander Cube |
| Tempt with Vengeance | `Create x <n>/<n> red elemental creature tokens with haste. each opponent may create x <n>/<n> red elemental creature tokens with haste. for each opponent who does, create x <n>/<n> red elemental creature tokens with haste.` |  |
| Thalisse, Reverent Medium | `At the beginning of each end step, create x <n>/<n> white spirit creature tokens with flying, where x is the number of tokens you created this turn.` |  |
| Twilight Drover | `Whenever a creature token leaves the battlefield, put a +<n>/+<n> counter on ~.` |  |
| Windbrisk Heights | `<cost>, <cost>: you may play the exiled card without paying its mana cost if you attacked with <n> or more creatures this turn.` |  |
| Within Range | `Whenever you attack, each opponent loses life equal to the number of creatures attacking them.` |  |
| Zurgo Stormrender | `Whenever a creature token you control leaves the battlefield, draw a card if it was attacking. otherwise, each opponent loses <n> life.` |  |


### Miracle Worker - Duskmourn: House of Horror Commander (28 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aminatou's Augury | `Exile the top <n> cards of your library. you may put a land card from among them onto the battlefield. until end of turn, for each nonland card type, you may cast a spell of that type from among the exiled cards without paying its mana cost.` |  |
| Aminatou, Veil Piercer | `Each enchantment card in your hand has miracle. its miracle cost is equal to its mana cost reduced by <cost>.` |  |
| Ancient Cellarspawn | Compound gap — `Each spell you cast that's a demon, horror, or nightmare costs <cost> less to cast.`; `Whenever you cast a spell, if the amount of mana spent to cast it was less than its mana value, target opponent loses life equal to the difference.` |  |
| Archetype of Imagination | `Creatures your opponents control lose flying and can't have or gain flying.` |  |
| Arvinox, the Mind Flail | Compound gap — `~ isn't a creature unless you control <n> or more permanents you don't own.`; `At the beginning of your end step, exile the bottom card of each opponent's library face down. for as long as those cards remain exiled, you may look at them, you may cast permanent spells from among them, and you may spend mana as though it were mana of any color to cast those spells.` |  |
| Athreos, Shroud-Veiled | Compound gap — `At the beginning of your end step, put a coin counter on another target creature.`; `Whenever a creature with a coin counter on it dies or is put into exile, return that card to the battlefield under your control.` |  |
| Bottomless Pool // Locker Room | `When you unlock this door, return up to <n> target creature to its owner's hand.` |  |
| Brainstone | `<cost>, <cost>, sacrifice ~: draw <n> cards, then put <n> cards from your hand on top of your library in any order.` |  |
| Cramped Vents // Access Maze | `When you unlock this door, this room deals <n> damage to target creature an opponent controls. you gain life equal to the excess damage dealt this way.` |  |
| Demon of Fate's Design | Compound gap — `<cost>, sacrifice another enchantment: ~ gets +x/+<n> until end of turn, where x is the sacrificed enchantment's mana value.`; `Once during each of your turns, you may cast an enchantment spell by paying life equal to its mana value rather than paying its mana cost.` |  |
| Dream Eater | `When ~ enters, surveil <n>. when you do, you may return target nonland permanent an opponent controls to its owner's hand.` |  |
| Extravagant Replication | `At the beginning of your upkeep, create a token that's a copy of another target nonland permanent you control.` |  |
| Fear of Sleep Paralysis | Compound gap — `Stun counters can't be removed from permanents your opponents control.`; `Whenever ~ or another enchantment you control enters and whenever you fully unlock a room, tap up to <n> target creature and put a stun counter on it.` |  |
| Hall of Heliod's Generosity | `<cost>, <cost>: put target enchantment card from your graveyard on top of your library.` |  |
| Life Insurance | `Whenever a nontoken creature dies, you lose <n> life and create a treasure token.` |  |
| Metamorphosis Fanatic | `When ~ enters, return up to <n> target creature card from your graveyard to the battlefield with a lifelink counter on it.` |  |
| Nightmare Shepherd | `Whenever another nontoken creature you control dies, you may exile it. if you do, create a token that's a copy of that creature, except it's <n>/<n> and it's a nightmare in addition to its other types.` |  |
| Ondu Spiritdancer | `Whenever an enchantment you control enters, you may create a token that's a copy of it. do this only once each turn.` |  |
| One with the Multiverse | `Once during each of your turns, you may cast a spell from your hand or the top of your library without paying its mana cost.` |  |
| Phenomenon Investigators | Compound gap — `As ~ enters, choose believe or doubt.`; `• believe — whenever a nontoken creature you control dies, create a <n>/<n> black horror enchantment creature token.`; `• doubt — at the beginning of your end step, you may return a nonland permanent you own to your hand. if you do, draw a card.` |  |
| Return to Dust | `Exile target artifact or enchantment. if you cast this spell during your main phase, you may exile up to <n> other target artifact or enchantment.` |  |
| Secret Arcade // Dusty Parlor | `Nonland permanents you control and permanent spells you control are enchantments in addition to their other types.` |  |
| Spirit-Sister's Call | `At the beginning of your end step, choose target permanent card in your graveyard. you may sacrifice a permanent that shares a card type with the chosen card. if you do, return the chosen card from your graveyard to the battlefield and it gains ~` |  |
| Telling Time | `Look at the top <n> cards of your library. put <n> of those cards into your hand, <n> on top of your library, and <n> on the bottom of your library.` |  |
| The Eldest Reborn | Compound gap — `I — each opponent sacrifices a creature or planeswalker of their choice.`; `Iii — put target creature or planeswalker card from a graveyard onto the battlefield under your control.` |  |
| The Master of Keys | Compound gap — `Each enchantment card in your graveyard has escape. the escape cost is equal to the card's mana cost plus exile <n> other cards from your graveyard.`; `When ~ enters, put x +<n>/+<n> counters on it and mill twice x cards.` |  |
| Thirst for Meaning | `Draw <n> cards. then discard <n> cards unless you discard an enchantment card.` |  |
| Verge Rangers | `As long as an opponent controls more lands than you, you may play lands from the top of your library.` |  |


### Oops! All Night's Whispers (19 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Agent of Treachery | Compound gap — `At the beginning of your end step, if you control <n> or more permanents you don't own, draw <n> cards.`; `When ~ enters, gain control of target permanent.` |  |
| Aphotic Wisps | `Target creature becomes black and gains fear until end of turn.` |  |
| Breach the Multiverse | `Each player mills <n> cards. for each player, choose a creature or planeswalker card in that player's graveyard. put those cards onto the battlefield under your control. then each creature you control becomes a phyrexian in addition to its other types.` |  |
| Coiling Rebirth | `Return target creature card from your graveyard to the battlefield. then if the gift was promised and that creature isn't legendary, create a token that's a copy of that creature, except it's <n>/<n>.` |  |
| Crimson Wisps | `Target creature becomes red and gains haste until end of turn.` |  |
| Exhume | `Each player puts a creature card from their graveyard onto the battlefield.` |  |
| Fable of the Mirror-Breaker // Reflection of Kiki-Jiki | Compound gap — `I — create a <n>/<n> red goblin shaman creature token with ~`; `Ii — you may discard up to <n> cards. if you do, draw that many cards.` | Also uncovered in: Commander Cube |
| Ghastly Demise | `Destroy target nonblack creature if its toughness is less than or equal to the number of cards in your graveyard.` |  |
| Glasses of Urza | `<cost>: look at target player's hand.` |  |
| Liquimetal Torque | `<cost>: target nonland permanent becomes an artifact in addition to its other types until end of turn.` | Also uncovered in: Commander Cube |
| Marchesa, Dealer of Death | `Whenever you commit a crime, you may pay <cost>. if you do, look at the top <n> cards of your library. put <n> of them into your hand and the other into your graveyard.` |  |
| Palantír of Orthanc | `At the beginning of your end step, put an influence counter on ~ and scry <n>. then target opponent may have you draw a card. if that player doesn't, you mill x cards, where x is the number of influence counters on ~, and that player loses life equal to the total mana value of those cards.` |  |
| Phyrexian Furnace | `<cost>: exile the bottom card of target player's graveyard.` |  |
| Prismari, the Inspiration | `Instant and sorcery spells you cast have storm.` |  |
| Ripples of Undeath | `At the beginning of your first main phase, mill <n> cards. then you may pay <cost> and <n> life. if you do, put a card from among those cards into your hand.` |  |
| Scholar of the Lost Trove | `When ~ enters, you may cast target instant, sorcery, or artifact card from your graveyard without paying its mana cost. if an instant or sorcery spell cast this way would be put into your graveyard, exile it instead.` |  |
| Sidisi, Undead Vizier | `When ~ exploits a creature, you may search your library for a card, put it into your hand, then shuffle.` |  |
| Stitch Together | `Return that card from your graveyard to the battlefield instead if there are <n> or more cards in your graveyard.` | Also uncovered in: Revival Trance - Final Fantasy Commander |
| Victimize | `Choose <n> target creature cards in your graveyard. sacrifice a creature. if you do, return the chosen cards to the battlefield tapped.` | Also uncovered in: Riveteer Rampage - New Capenna Commander, Sultai Arisen - Tarkir: Dragonstorm Commander |


### Peace Offering - Bloomburrow Commander (26 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bloodroot Apothecary | Compound gap — `When ~ enters, you and target opponent each create a treasure token.`; `Whenever an opponent sacrifices a noncreature token, that player gets <n> poison counters.` |  |
| Coiling Oracle | `When ~ enters, reveal the top card of your library. if it's a land card, put it onto the battlefield. otherwise, put that card into your hand.` |  |
| Communal Brewing | Compound gap — `When ~ enters, any number of target opponents each draw a card. put an ingredient counter on ~, then put an ingredient counter on it for each card drawn this way.`; `Whenever you cast a creature spell, that creature enters with x additional +<n>/+<n> counters on it, where x is the number of ingredient counters on ~.` |  |
| Coveted Jewel | `Whenever <n> or more creatures an opponent controls attack you and aren't blocked, that player draws <n> cards and gains control of ~. untap it.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Fisher's Talent | Compound gap — `At the beginning of your upkeep, look at the top card of your library. you may reveal it if it's a land card. create a <n>/<n> blue fish creature token if you revealed it this way. then draw a card.`; `If you would create a fish token, create a <n>/<n> blue shark creature token instead.`; `If you would create a shark token, create an <n>/<n> blue octopus creature token instead.` |  |
| Generous Gift | `Destroy target permanent. its controller creates a <n>/<n> green elephant creature token.` | Also uncovered in: yshtola |
| Ghirapur Orrery | `At the beginning of each player's upkeep, if that player has no cards in hand, that player draws <n> cards.` |  |
| Illusionist's Gambit | Compound gap — `Cast this spell only during the declare blockers step on an opponent's turn.`; `Remove all attacking creatures from combat and untap them. after this phase, there is an additional combat phase. each of those creatures attacks that combat if able. they can't attack you or planeswalkers you control that combat.` |  |
| Intellectual Offering | Compound gap — `Choose an opponent. untap all nonland permanents you control and all nonland permanents that player controls.`; `Choose an opponent. you and that player each draw <n> cards.` |  |
| Jolly Gerbils | `Whenever you give a gift, draw a card.` |  |
| Jolrael, Mwonvuli Recluse | `<cost>: until end of turn, creatures you control have base power and toughness x/x, where x is the number of cards in your hand.` |  |
| Kwain, Itinerant Meddler | `<cost>: each player may draw a card, then each player who drew a card this way gains <n> life.` |  |
| Long River's Pull | `Counter target creature spell. if the gift was promised, instead counter target spell.` |  |
| Mr. Foxglove | `Whenever ~ attacks, draw cards equal to the number of cards in defending player's hand minus the number of cards in your hand. if you didn't draw cards this way, you may put a creature card from your hand onto the battlefield.` |  |
| Ms. Bumbleflower | `Whenever you cast a spell, target opponent draws a card. put a +<n>/+<n> counter on target creature. it gains flying until end of turn. if this is the second time this ability has resolved this turn, you draw <n> cards.` |  |
| Octomancer | `At the beginning of each end step, create a token that's a copy of target creature token that entered the battlefield this turn.` |  |
| Peerless Recycling | `Return target permanent card from your graveyard to your hand. if the gift was promised, instead return <n> target permanent cards from your graveyard to your hand.` |  |
| Perch Protection | `Create <n> <n>/<n> blue bird creature tokens with flying. if the gift was promised, all permanents you control phase out, and until your next turn, your life total can't change and you gain protection from everything.` |  |
| Rishkar, Peema Renegade | `Each creature you control with a counter on it has ~` | Also uncovered in: Commander Cube, Raggadragga, Goreguts Boss |
| Selvala, Explorer Returned | `<cost>: each player reveals the top card of their library. for each nonland card revealed this way, add <cost> and you gain <n> life. then each player draws a card.` |  |
| Tempt with Bunnies | `Draw a card and create a <n>/<n> white rabbit creature token. then each opponent may draw a card and create a <n>/<n> white rabbit creature token. for each opponent who does, you draw a card and you create a <n>/<n> white rabbit creature token.` |  |
| Tempt with Discovery | `Search your library for a land card and put it onto the battlefield. each opponent may search their library for a land card and put it onto the battlefield. for each opponent who searches a library this way, search your library for a land card and put it onto the battlefield. then each player who searched a library this way shuffles.` |  |
| Tenuous Truce | Compound gap — `At the beginning of enchanted opponent's end step, you and that player each draw a card.`; `When you attack enchanted opponent or a planeswalker they control or when they attack you or a planeswalker you control, sacrifice ~.` |  |
| Triskaidekaphile | `At the beginning of your upkeep, if you have exactly thirteen cards in your hand, you win the game.` |  |
| Twenty-Toed Toad | Compound gap — `Whenever ~ attacks, you win the game if there are twenty or more counters on it or you have twenty or more cards in hand.`; `Whenever you attack with <n> or more creatures, put a +<n>/+<n> counter on ~ and draw a card.`; `Your maximum hand size is twenty.` |  |
| Wear Down | `Destroy target artifact or enchantment. if the gift was promised, instead destroy <n> target artifacts and/or enchantments.` | Also uncovered in: Commander Cube |


### Raggadragga, Goreguts Boss (19 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Akroma's Memorial | `Creatures you control have flying, first strike, vigilance, trample, haste, and protection from black and from red.` |  |
| Awaken the Woods | `Create x <n>/<n> green forest dryad land creature tokens.` | Also uncovered in: Commander Cube |
| Benefactor's Draught | `Untap all creatures. until end of turn, whenever a creature an opponent controls blocks, draw a card.` |  |
| Freyalise, Llanowar's Fury | Compound gap — `+<n>: create a <n>/<n> green elf druid creature token with ~`; `−<n>: draw a card for each green creature you control.` |  |
| Genesis Wave | `Reveal the top x cards of your library. you may put any number of permanent cards with mana value x or less from among them onto the battlefield. then put all cards revealed this way that weren't put onto the battlefield into your graveyard.` |  |
| Glimpse of Nature | `Whenever you cast a creature spell this turn, draw a card.` |  |
| Gwenna, Eyes of Gaea | `Whenever you cast a creature spell with power <n> or greater, put a +<n>/+<n> counter on ~ and untap it.` | Also uncovered in: Commander Cube, SpongeBob and the legendary Burger |
| Last March of the Ents | `Draw cards equal to the greatest toughness among creatures you control, then put any number of creature cards from your hand onto the battlefield.` |  |
| March of the World Ooze | Compound gap — `Creatures you control have base power and toughness <n>/<n> and are oozes in addition to their other types.`; `Whenever an opponent casts a spell, if it's not their turn, you create a <n>/<n> green elephant creature token.` |  |
| Orochi Merge-Keeper | `As long as ~ is modified, it has ~` |  |
| Raggadragga, Goreguts Boss | Compound gap — `Each creature you control with a mana ability gets +<n>/+<n>.`; `Whenever a creature you control with a mana ability attacks, untap it.`; `Whenever you cast a spell, if at least <n> mana was spent to cast it, untap target creature. it gets +<n>/+<n> and gains trample until end of turn.` |  |
| Regal Force | `When ~ enters, draw a card for each green creature you control.` |  |
| Rishkar's Expertise | `Draw cards equal to the greatest power among creatures you control.` |  |
| Saryth, the Viper's Fang | `<cost>, <cost>: untap another target creature or land you control.` |  |
| Stonehoof Chieftain | `Whenever another creature you control attacks, it gains trample and indestructible until end of turn.` |  |
| Turntimber Symbiosis // Turntimber, Serpentine Wood | `Look at the top <n> cards of your library. you may put a creature card from among them onto the battlefield. if that card has mana value <n> or less, it enters with <n> additional +<n>/+<n> counters on it. put the rest on the bottom of your library in a random order.` | Also uncovered in: Commander Cube |
| Twitching Doll | `<cost>, sacrifice ~: create a <n>/<n> green spider creature token with reach for each counter on ~. activate only as a sorcery.` | Also uncovered in: Commander Cube |
| Wirewood Herald | `When ~ dies, you may search your library for an elf card, reveal that card, put it into your hand, then shuffle.` |  |
| Yarus, Roar of the Old Gods | Compound gap — `Whenever <n> or more face-down creatures you control deal combat damage to a player, draw a card.`; `Whenever a face-down creature you control dies, return it to the battlefield face down under its owner's control if it's a permanent card, then turn it face up.` |  |


### Revival Trance - Final Fantasy Commander (29 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Archfiend of Depravity | `At the beginning of each opponent's end step, that player chooses up to <n> creatures they control, then sacrifices the rest.` |  |
| Banon, the Returners' Leader | Compound gap — `Once during each of your turns, you may cast a creature spell from among cards in your graveyard that were put there from anywhere other than the battlefield this turn.`; `Whenever you attack, you may pay <cost> and discard a card. if you do, draw a card.` |  |
| Coin of Fate | `<cost>, <cost>, exile <n> creature cards from your graveyard, sacrifice ~: an opponent chooses <n> of the exiled cards. you put that card on the bottom of your library and return the other to the battlefield tapped. you become the monarch.` |  |
| Crackling Doom | `~ deals <n> damage to each opponent. each opponent sacrifices a creature with the greatest power among creatures that player controls.` |  |
| Cyan, Vengeful Samurai | `Whenever <n> or more creature cards leave your graveyard, put a +<n>/+<n> counter on ~.` |  |
| Demolition Field | `<cost>, <cost>, sacrifice ~: destroy target nonbasic land an opponent controls. that land's controller may search their library for a basic land card, put it onto the battlefield, then shuffle. you may search your library for a basic land card, put it onto the battlefield, then shuffle.` | Also uncovered in: Scions & Spellcraft - Final Fantasy Commander |
| Espers to Magicite | `Exile each opponent's graveyard. when you do, choose up to <n> target creature card exiled this way. create a token that's a copy of that card, except it's an artifact and it loses all other card types.` |  |
| Flayer of the Hatebound | `Whenever ~ or another creature enters from your graveyard, that creature deals damage equal to its power to any target.` |  |
| Gau, Feral Youth | `At the beginning of each end step, if a card left your graveyard this turn, ~ deals damage equal to its power to each opponent.` |  |
| Gogo, Mysterious Mime | `At the beginning of combat on your turn, you may have ~ become a copy of another target creature you control until end of turn, except its name is ~. if you do, ~ and that creature each get +<n>/+<n> and gain haste until end of turn and attack this turn if able.` |  |
| Kefka, Dancing Mad | `At the beginning of your end step, exile a card at random from each opponent's graveyard. you may cast any number of spells from among cards exiled this way without paying their mana costs. then each player who owns a spell you cast this way loses life equal to its mana value.` |  |
| Legions to Ashes | `Exile target nonland permanent an opponent controls and all tokens that player controls with the same name as that permanent.` |  |
| Locke, Treasure Hunter | `Whenever ~ attacks, each player mills a card. if a land card was milled this way, create a treasure token. until end of turn, you may cast a spell from among those cards.` |  |
| Mog, Moogle Warrior | `At the beginning of your end step, each player may discard a card. each player who discarded a card this way draws a card. if a creature card was discarded this way, you create a <n>/<n> white moogle creature token with lifelink. then if a noncreature card was discarded this way, put a +<n>/+<n> counter on each moogle you control.` |  |
| Palace Jailer | `When ~ enters, exile target creature an opponent controls until an opponent becomes the monarch.` | Also uncovered in: Commander Cube |
| Phoenix Down | Compound gap — `<cost>, <cost>, exile ~: choose <n> —`; `• exile target skeleton, spirit, or zombie.`; `• return target creature card with mana value <n> or less from your graveyard to the battlefield tapped.` |  |
| Rejoin the Fight | `Mill <n> cards. then starting with the next opponent in turn order, each opponent chooses a creature card in your graveyard that hasn't been chosen. return each card chosen this way to the battlefield under your control.` |  |
| Rise of the Dark Realms | `Put all creature cards from all graveyards onto the battlefield under your control.` |  |
| Ruin Grinder | `When ~ dies, each player may discard their hand and draw <n> cards.` |  |
| Ruinous Ultimatum | `Destroy all nonland permanents your opponents control.` |  |
| Sepulchral Primordial | `When ~ enters, for each opponent, you may put up to <n> target creature card from that player's graveyard onto the battlefield under your control.` |  |
| Setzer, Wandering Gambler | Compound gap — `When ~ enters, create the blackjack, a legendary <n>/<n> colorless vehicle artifact token with flying and crew <n>.`; `Whenever a vehicle you control deals combat damage to a player, flip a coin.`; `Whenever you win a coin flip, create <n> tapped treasure tokens.` |  |
| Shadow, Mysterious Assassin | `Throw — whenever ~ deals combat damage to a player, you may sacrifice another nonland permanent. if you do, draw <n> cards and each opponent loses life equal to the mana value of the sacrificed permanent.` |  |
| Siegfried, Famed Swordsman | `When ~ enters, mill <n> cards. then put x +<n>/+<n> counters on ~, where x is twice the number of creature cards in your graveyard.` |  |
| Snort | `Each player may discard their hand and draw <n> cards. then ~ deals <n> damage to each opponent who discarded their hand this way.` |  |
| Strago and Relm | `<cost>, <cost>: target opponent exiles cards from the top of their library until they exile an instant, sorcery, or creature card. you may cast that card without paying its mana cost. if you cast a creature spell this way, it gains haste and ~ activate only as a sorcery.` |  |
| Summon: Esper Valigarmanda | Compound gap — `I — exile an instant or sorcery card from each graveyard.`; `Ii, iii, iv — add <cost> for each lore counter on this saga. you may cast an instant or sorcery card exiled with this saga, and mana of any type can be spent to cast that spell.` |  |
| Terra, Herald of Hope | `Whenever ~ deals combat damage to a player, you may pay <cost>. when you do, return target creature card with power <n> or less from your graveyard to the battlefield tapped.` |  |
| The Warring Triad | Compound gap — `<cost>, mill a card: target player adds <n> mana of any color.`; `As long as there are fewer than <n> cards in your graveyard, ~ isn't a creature.` |  |


### Riveteer Rampage - New Capenna Commander (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aether Snap | `Remove all counters from all permanents and exile all tokens.` |  |
| Bellowing Mauler | `At the beginning of your end step, each player loses <n> life unless they sacrifice a nontoken creature of their choice.` |  |
| Caldaia Guardian | `Whenever ~ or another creature you control with mana value <n> or greater dies, create <n> <n>/<n> green and white citizen creature tokens.` |  |
| Deathbringer Regent | `When ~ enters, if you cast it from your hand and there are <n> or more other creatures on the battlefield, destroy all other creatures.` |  |
| Disciple of Bolas | `When ~ enters, sacrifice another creature. you gain x life and draw x cards, where x is that creature's power.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander, Wick Snail Boom |
| First Responder | `At the beginning of your end step, you may return another creature you control to its owner's hand, then put a number of +<n>/+<n> counters equal to that creature's power on ~.` |  |
| Grime Gorger | `Whenever ~ attacks, exile up to <n> card of each card type from defending player's graveyard. put a +<n>/+<n> counter on ~ for each card exiled this way.` |  |
| Henzie "Toolbox" Torre | `Each creature spell you cast with mana value <n> or greater has blitz. the blitz cost is equal to its mana cost.` |  |
| Industrial Advancement | `At the beginning of your end step, you may sacrifice a creature. if you do, look at the top x cards of your library, where x is that creature's mana value. you may put a creature card from among them onto the battlefield. put the rest on the bottom of your library in a random order.` |  |
| Kresh the Bloodbraided | `Whenever another creature dies, you may put x +<n>/+<n> counters on ~, where x is that creature's power.` |  |
| Life's Legacy | `Draw cards equal to the sacrificed creature's power.` |  |
| Mezzio Mugger | `Whenever ~ attacks, exile the top card of each player's library. you may play those cards this turn, and you may spend mana as though it were mana of any color to cast those spells.` |  |
| Mitotic Slime | `When ~ dies, create <n> <n>/<n> green ooze creature tokens. they have ~` |  |
| Next of Kin | `When enchanted creature dies, you may put a creature card you own with lesser mana value from your hand or from the command zone onto the battlefield. if you do, return this card to the battlefield attached to that creature at the beginning of the next end step.` |  |
| Protection Racket | `At the beginning of your upkeep, repeat the following process for each opponent in turn order. reveal the top card of your library. that player may pay life equal to that card's mana value. if they do, exile that card. otherwise, put it into your hand.` |  |
| Stalking Vengeance | `Whenever another creature you control dies, it deals damage equal to its power to target player or planeswalker.` |  |
| The Beamtown Bullies | `<cost>: target opponent whose turn it is puts target nonlegendary creature card from your graveyard onto the battlefield under their control. it gains haste. goad it. at the beginning of the next end step, exile it.` |  |
| Turf War | Compound gap — `When ~ enters, for each player, put a contested counter on target land that player controls.`; `Whenever a creature deals combat damage to a player, if that player controls <n> or more lands with contested counters on them, that creature's controller gains control of <n> of those lands of their choice and untaps it.` |  |
| Wave of Rats | `When ~ dies, if it dealt combat damage to a player this turn, return it to the battlefield under its owner's control.` |  |
| Windgrace's Judgment | `For any number of opponents, destroy target nonland permanent that player controls.` | Also uncovered in: Squirreled Away - Bloomburrow Commander, World Shaper - Edge of Eternities Commander Deck |
| Woodfall Primus | `When ~ enters, destroy target noncreature permanent.` |  |
| World Shaper | `When ~ dies, return all land cards from your graveyard to the battlefield tapped.` |  |


### Scions & Spellcraft - Final Fantasy Commander (24 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Ardbert, Warrior of Darkness | Compound gap — `Whenever you cast a black spell, put a +<n>/+<n> counter on each legendary creature you control. they gain menace until end of turn.`; `Whenever you cast a white spell, put a +<n>/+<n> counter on each legendary creature you control. they gain vigilance until end of turn.` |  |
| Astrologian's Planisphere | `Equipped creature is a wizard in addition to its other types and has ~` |  |
| Blue Mage's Cane | `Equipped creature gets +<n>/+<n>, is a wizard in addition to its other types, and has ~` |  |
| Champions from Beyond | Compound gap — `When ~ enters, create x <n>/<n> colorless hero creature tokens.`; `Whenever you attack with <n> or more creatures, scry <n>, then draw a card.`; `Whenever you attack with <n> or more creatures, those creatures get +<n>/+<n> until end of turn.` |  |
| Circle of Power | Compound gap — `Wizards you control get +<n>/+<n> and gain lifelink until end of turn.`; `You draw <n> cards and you lose <n> life. create a <n>/<n> black wizard creature token with ~` |  |
| Dancer's Chakrams | `Equipped creature gets +<n>/+<n>, has lifelink and ~ and is a performer in addition to its other types.` |  |
| Estinien Varlineau | `At the beginning of your second main phase, you draw x cards and lose x life, where x is the number of your opponents who were dealt combat damage by ~ or a dragon this turn.` |  |
| Eye of Nidhogg | `Enchanted creature is a black dragon with base power and toughness <n>/<n>, has flying and deathtouch, and is goaded.` |  |
| Fandaniel, Telophoroi Ascian | `At the beginning of your end step, each opponent may sacrifice a nontoken creature of their choice. each opponent who doesn't loses <n> life for each instant and sorcery card in your graveyard.` | Also uncovered in: yshtola |
| G'raha Tia, Scion Reborn | `Whenever you cast a noncreature spell, you may pay x life, where x is that spell's mana value. if you do, create a <n>/<n> colorless hero creature token and put x +<n>/+<n> counters on it. do this only once each turn.` |  |
| Hermes, Overseer of Elpis | `Whenever you attack with <n> or more birds, scry <n>.` |  |
| Krile Baldesion | `Whenever you cast a noncreature spell, you may return target creature card with mana value equal to that spell's mana value from your graveyard to your hand. do this only once each turn.` |  |
| Lethal Scheme | `Destroy target creature or planeswalker. each creature that convoked this spell connives.` | Also uncovered in: Commander Cube, Sultai Arisen - Tarkir: Dragonstorm Commander |
| Lyse Hext | `As long as you've cast <n> or more noncreature spells this turn, ~ has double strike.` |  |
| Observed Stasis | Compound gap — `Enchanted creature loses all abilities and can't attack or block.`; `When ~ enters, remove enchanted creature from combat. then draw a card for each tapped creature its controller controls.` |  |
| Papalymo Totolymo | `<cost>, <cost>, sacrifice ~: each opponent who lost life this turn sacrifices a creature with the greatest power among creatures they control.` |  |
| Reaper's Scythe | Compound gap — `At the beginning of your end step, put a soul counter on ~ for each player who lost life this turn.`; `Equipped creature gets +<n>/+<n> for each soul counter on ~ and is an assassin in addition to its other types.` |  |
| Summon: Good King Mog XII | Compound gap — `Ii, iii — whenever you cast a noncreature spell this turn, create a token that's a copy of a non-saga token you control.`; `Iv — put <n> +<n>/+<n> counters on each other moogle you control.` |  |
| Thancred Waters | `When ~ enters, another target legendary permanent you control gains indestructible for as long as you control ~.` |  |
| Tome of Legends | `Whenever your commander enters or attacks, put a page counter on ~.` |  |
| Torrential Gearhulk | `When ~ enters, you may cast target instant card from your graveyard without paying its mana cost. if that spell would be put into your graveyard, exile it instead.` |  |
| Transpose | `Draw a card, then discard a card. you lose <n> life. if this spell was cast from your hand, create a <n>/<n> black wizard creature token with ~` |  |
| Urianger Augurelt | Compound gap — `<cost>: look at the top card of your library. you may exile it face down.`; `<cost>: until end of turn, you may play cards exiled with ~. spells you cast this way cost <cost> less to cast.`; `Whenever you play a land from exile or cast a spell from exile, you gain <n> life.` |  |
| Y'shtola, Night's Blessed | Compound gap — `At the beginning of each end step, if a player lost <n> or more life this turn, you draw a card.`; `Whenever you cast a noncreature spell with mana value <n> or greater, ~ deals <n> damage to each opponent and you gain <n> life.` | Also uncovered in: yshtola |


### Shorikai Vehicles (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aerial Surveyor | `Whenever ~ attacks, if defending player controls more lands than you, search your library for a basic plains card, put it onto the battlefield tapped, then shuffle.` |  |
| Born to Drive | Compound gap — `<cost>, discard this card: create <n> <n>/<n> colorless pilot creature tokens with ~`; `As long as enchanted permanent is a creature, it gets +<n>/+<n> for each creature and/or vehicle you control.` |  |
| Dermotaxi | Compound gap — `As ~ enters, exile a creature card from a graveyard.`; `Tap <n> untapped creatures you control: until end of turn, ~ becomes a copy of the exiled card, except it's a vehicle artifact in addition to its other types.` |  |
| Digsite Engineer | `Whenever you cast an artifact spell, you may pay <cost>. if you do, create a <n>/<n> colorless construct artifact creature token with ~` | Also uncovered in: Commander Cube |
| Mech Hangar | `<cost>, <cost>: target vehicle becomes an artifact creature until end of turn.` |  |
| Mechtitan Core | `<cost>, exile ~ and <n> other artifact creatures and/or vehicles you control: create mechtitan, a legendary <n>/<n> construct artifact creature token with flying, vigilance, trample, lifelink, and haste that's all colors. when that token leaves the battlefield, return all cards exiled with ~ except this card to the battlefield tapped under their owners' control.` |  |
| Mobile Garrison | `Whenever ~ attacks, untap another target artifact or creature you control.` |  |
| Mobilizer Mech | `Whenever ~ becomes crewed, up to <n> other target vehicle you control becomes an artifact creature until end of turn.` |  |
| Mutavault | `<cost>: ~ becomes a <n>/<n> creature with all creature types until end of turn. it's still a land.` |  |
| Padeem, Consul of Innovation | `At the beginning of your upkeep, if you control the artifact with the greatest mana value or tied for the greatest mana value, draw a card.` |  |
| Peacewalker Colossus | `<cost>: another target vehicle you control becomes an artifact creature until end of turn.` |  |
| Prodigy's Prototype | `Whenever <n> or more vehicles you control attack, create a <n>/<n> colorless pilot creature token with ~` |  |
| Rebbec, Architect of Ascension | `Artifacts you control have protection from each mana value among artifacts you control.` |  |
| Reckoner Bankbuster | `<cost>, <cost>, remove a charge counter from ~: draw a card. then if there are no charge counters on ~, create a treasure token and a <n>/<n> colorless pilot creature token with ~` |  |
| Replication Specialist | `Whenever a nontoken artifact you control enters, you may pay <cost>. if you do, create a token that's a copy of that artifact.` |  |
| Shorikai, Genesis Engine | `<cost>, <cost>: draw <n> cards, then discard a card. create a <n>/<n> colorless pilot creature token with ~` |  |
| Smuggler's Copter | `Whenever ~ attacks or blocks, you may draw a card. if you do, discard a card.` | Also uncovered in: Commander Cube |
| Surgehacker Mech | `When ~ enters, it deals damage equal to twice the number of vehicles you control to target creature or planeswalker an opponent controls.` |  |
| The Millennium Calendar | Compound gap — `When there are <n>,<n> or more time counters on ~, sacrifice it and each opponent loses <n>,<n> life.`; `Whenever you untap <n> or more permanents during your untap step, put that many time counters on ~.` |  |
| The Wanderer | `Prevent all noncombat damage that would be dealt to you and other permanents you control.` |  |
| Unwinding Clock | `Untap all artifacts you control during each other player's untap step.` |  |
| Weatherlight | `Whenever ~ deals combat damage to a player, look at the top <n> cards of your library. you may reveal a historic card from among them and put it into your hand. put the rest on the bottom of your library in a random order.` |  |


### SpongeBob and the legendary Burger (22 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Annie Joins Up | `If a triggered ability of a legendary creature you control triggers, that ability triggers an additional time.` |  |
| Atraxa, Grand Unifier | `When ~ enters, reveal the top <n> cards of your library. for each card type, you may put a card of that type from among the revealed cards into your hand. put the rest on the bottom of your library in a random order.` |  |
| Captain Sisay | `<cost>: search your library for a legendary card, reveal that card, put it into your hand, then shuffle.` |  |
| Chromatic Orrery | Compound gap — `<cost>, <cost>: draw a card for each color among permanents you control.`; `You may spend mana as though it were mana of any color.` |  |
| Desynchronization | `Return each nonland permanent that's not historic to its owner's hand.` |  |
| Dihada, Binder of Wills | Compound gap — `+<n>: up to <n> target legendary creature gains vigilance, lifelink, and indestructible until your next turn.`; `−<n>: gain control of all nonland permanents until end of turn. untap them. they gain haste until end of turn.`; `−<n>: reveal the top <n> cards of your library. put any number of legendary cards from among them into your hand and the rest into your graveyard. create a treasure token for each card put into your graveyard this way.` |  |
| Esika, God of the Tree // The Prismatic Bridge | `Other legendary creatures you control have vigilance and ~` |  |
| Hajar, Loyal Bodyguard | `Sacrifice ~: legendary creatures you control get +<n>/+<n> and gain indestructible until end of turn.` |  |
| Helga, Skittish Seer | `Whenever you cast a creature spell with mana value <n> or greater, you draw a card, gain <n> life, and put a +<n>/+<n> counter on ~.` |  |
| Kellan, the Kid | `Whenever you cast a spell from anywhere other than your hand, you may cast a permanent spell with equal or lesser mana value from your hand without paying its mana cost. if you don't, you may put a land card from your hand onto the battlefield.` |  |
| Kethis, the Hidden Hand | Compound gap — `Exile <n> legendary cards from your graveyard: until end of turn, each legendary card in your graveyard gains ~`; `Legendary spells you cast cost <cost> less to cast.` |  |
| Ramos, Dragon Engine | `Whenever you cast a spell, put a +<n>/+<n> counter on ~ for each of that spell's colors.` |  |
| Ratadrabik of Urborg | `Whenever another legendary creature you control dies, create a token that's a copy of that creature, except it's not legendary and it's a <n>/<n> black zombie in addition to its other colors and types.` |  |
| Reki, the History of Kamigawa | `Whenever you cast a legendary spell, draw a card.` |  |
| Serah Farron // Crystallized Serah | Compound gap — `At the beginning of combat on your turn, if you control <n> or more other legendary creatures, you may transform ~.`; `The first legendary creature spell you cast each turn costs <cost> less to cast.` |  |
| Shanid, Sleepers' Scourge | `Whenever you play a legendary land or cast a legendary spell, you draw a card and you lose <n> life.` |  |
| Sisay, Weatherlight Captain | Compound gap — `<cost>: search your library for a legendary permanent card with mana value less than ~'s power, put that card onto the battlefield, then shuffle.`; `~ gets +<n>/+<n> for each color among other legendary permanents you control.` |  |
| Tam, Mindful First-Year | Compound gap — `<cost>: target creature you control becomes all colors until end of turn.`; `Each other creature you control has hexproof from each of its colors.` |  |
| Tamiyo, Inquisitive Student // Tamiyo, Seasoned Scholar | `When you draw your third card in a turn, exile ~, then return her to the battlefield transformed under her owner's control.` |  |
| Urza's Ruinous Blast | `Exile all nonland permanents that aren't legendary.` |  |
| Venser, the Sojourner | `+<n>: exile target permanent you own. return it to the battlefield under your control at the beginning of the next end step.` |  |
| Vraska Joins Up | Compound gap — `When ~ enters, put a deathtouch counter on each creature you control.`; `Whenever a legendary creature you control deals combat damage to a player, draw a card.` |  |


### Squirreled Away - Bloomburrow Commander (24 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Cache Grab | `Mill <n> cards. you may put a permanent card from among the cards milled this way into your hand. if you control a squirrel or returned a squirrel card to your hand this way, create a food token.` |  |
| Chatterfang, Squirrel General | Compound gap — `<cost>, sacrifice x squirrels: target creature gets +x/-x until end of turn.`; `If <n> or more tokens would be created under your control, those tokens plus that many <n>/<n> green squirrel creature tokens are created instead.` |  |
| Chitterspitter | Compound gap — `At the beginning of your upkeep, you may sacrifice a token. if you do, put an acorn counter on ~.`; `Squirrels you control get +<n>/+<n> for each acorn counter on ~.` |  |
| Garruk, Cursed Huntsman | `<n>: create <n> <n>/<n> black and green wolf creature tokens with ~` |  |
| Gourmand's Talent | `During your turn, artifacts you control are foods in addition to their other types and have ~` |  |
| Hazel of the Rootbloom | `At the beginning of your end step, create a token that's a copy of target token you control. if that token is a squirrel, instead create <n> tokens that are copies of it.` |  |
| Hazel's Brewmaster | `Foods you control have all activated abilities of all creature cards exiled with ~.` |  |
| Honored Dreyleader | `When ~ enters, put a +<n>/+<n> counter on it for each other squirrel and/or food you control.` |  |
| Insatiable Frugivore | Compound gap — `<cost>, sacrifice x foods: creatures you control get +x/+<n> and gain menace until end of turn.`; `When ~ enters, create a food token, then you may exile <n> cards from your graveyard. if you do, repeat this process.` |  |
| Maelstrom Pulse | `Destroy target nonland permanent and all other permanents with the same name as that permanent.` |  |
| Moonstone Eulogist | `Whenever you sacrifice an artifact, put a +<n>/+<n> counter on ~ and you gain <n> life.` |  |
| Nested Shambler | `When ~ dies, create x tapped <n>/<n> green squirrel creature tokens, where x is ~'s power.` |  |
| Ogre Slumlord | `Whenever another nontoken creature dies, you may create a <n>/<n> black rat creature token.` |  |
| Plaguecrafter | `When ~ enters, each player sacrifices a creature or planeswalker of their choice. each player who can't discards a card.` |  |
| Ravenous Squirrel | `Whenever you sacrifice an artifact or creature, put a +<n>/+<n> counter on ~.` |  |
| Saw in Half | `Destroy target creature. if that creature dies this way, its controller creates <n> tokens that are copies of that creature, except their power is half that creature's power and their toughness is half that creature's toughness. round up each time.` |  |
| Second Harvest | `For each token you control, create a token that's a copy of that permanent.` |  |
| Shamanic Revelation | `You gain <n> life for each creature you control with power <n> or greater.` |  |
| Skyfisher Spider | `When ~ dies, you may gain <n> life for each creature card in your graveyard. if you do, exile this card from your graveyard.` |  |
| Swarmyard | `<cost>: regenerate target insect, rat, spider, or squirrel.` |  |
| Swarmyard Massacre | `Create <n> <n>/<n> green squirrel creature tokens. then each creature that isn't an insect, rat, spider, or squirrel gets -<n>/-<n> until end of turn for each creature you control that's an insect, rat, spider, or squirrel.` |  |
| Sword of the Squeak | Compound gap — `Equipped creature gets +<n>/+<n> for each creature you control with base power or toughness <n>.`; `Whenever a hamster, mouse, rat, or squirrel you control enters, you may attach ~ to that creature.` |  |
| Tear Asunder | `Exile target artifact or enchantment. if this spell was kicked, exile target nonland permanent instead.` | Also uncovered in: Sultai Arisen - Tarkir: Dragonstorm Commander, World Shaper - Edge of Eternities Commander Deck |
| The Odd Acorn Gang | Compound gap — `Squirrels you control have ~`; `Whenever <n> or more squirrels you control deal combat damage to a player, draw a card.` |  |


### Sultai Arisen - Tarkir: Dragonstorm Commander (20 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Afterlife from the Loam | `For each player, choose up to <n> target creature card in that player's graveyard. put those cards onto the battlefield under your control. they're zombies in addition to their other types.` |  |
| Amphin Mutineer | `When ~ enters, exile up to <n> target non-salamander creature. that creature's controller creates a <n>/<n> blue salamander warrior creature token.` | Also uncovered in: Commander Cube |
| Colossal Grave-Reaver | `Whenever <n> or more creature cards are put into your graveyard from your library, put <n> of them onto the battlefield.` | Also uncovered in: Commander Cube |
| Consuming Aberration | Compound gap — `~'s power and toughness are each equal to the number of cards in your opponents' graveyards.`; `Whenever you cast a spell, each opponent reveals cards from the top of their library until they reveal a land card, then puts those cards into their graveyard.` |  |
| Diviner of Mist | `Whenever ~ attacks, mill <n> cards. you may cast an instant or sorcery spell from your graveyard with mana value <n> or less without paying its mana cost. if that spell would be put into your graveyard, exile it instead.` |  |
| Essence Anchor | `<cost>: create a <n>/<n> black zombie druid creature token. activate only during your turn and only if a card left your graveyard this turn.` |  |
| Floral Evoker | `<cost>, discard a creature card: return target land card from your graveyard to the battlefield tapped.` |  |
| Jarad, Golgari Lich Lord | `<cost>, sacrifice another creature: each opponent loses life equal to the sacrificed creature's power.` |  |
| Kishla Skimmer | `Whenever a card leaves your graveyard during your turn, draw a card. this ability triggers only once each turn.` |  |
| Kotis, Sibsig Champion | Compound gap — `Once during each of your turns, you may cast a creature spell from your graveyard by exiling <n> other cards from your graveyard in addition to paying its other costs.`; `Whenever <n> or more creatures you control enter, if <n> or more of them entered from a graveyard or was cast from a graveyard, put <n> +<n>/+<n> counters on ~.` |  |
| Lord of Extinction | `~'s power and toughness are each equal to the number of cards in all graveyards.` |  |
| Meren of Clan Nel Toth | Compound gap — `At the beginning of your end step, choose target creature card in your graveyard. if that card's mana value is less than or equal to the number of experience counters you have, return it to the battlefield. otherwise, put it into your hand.`; `Whenever another creature you control dies, you get an experience counter.` |  |
| Necromantic Selection | `Destroy all creatures, then return a creature card put into a graveyard this way to the battlefield under your control. it's a black zombie in addition to its other colors and types. exile ~.` |  |
| Ob Nixilis, the Fallen | `Whenever a land you control enters, you may have target player lose <n> life. if you do, put <n> +<n>/+<n> counters on ~.` |  |
| River Kelpie | Compound gap — `Whenever ~ or another permanent enters from a graveyard, draw a card.`; `Whenever a player casts a spell from a graveyard, draw a card.` |  |
| Satyr Wayfinder | `When ~ enters, reveal the top <n> cards of your library. you may put a land card from among them into your hand. put the rest into your graveyard.` | Also uncovered in: Commander Cube, World Shaper - Edge of Eternities Commander Deck |
| Steward of the Harvest | Compound gap — `Creatures you control have all activated abilities of all land cards exiled with ~.`; `When ~ enters, exile up to <n> target land cards from your graveyard.` |  |
| Tasigur, the Golden Fang | `<cost>: mill <n> cards, then return a nonland card of an opponent's choice from your graveyard to your hand.` |  |
| Teval, the Balanced Scale | `Whenever ~ attacks, mill <n> cards. then you may return a land card from your graveyard to the battlefield tapped.` |  |
| Welcome the Dead | `Draw <n> cards, then discard a card and you lose <n> life. create x tapped <n>/<n> black zombie druid creature tokens, where x is the number of cards that were put into your graveyard from your hand or library this turn.` |  |


### Temur Roar - Tarkir: Dragonstorm Commander (35 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Atarka, World Render | `Whenever a dragon you control attacks, it gains double strike until end of turn.` | Also uncovered in: Commander Cube |
| Become the Avalanche | `Draw a card for each creature you control with power <n> or greater. then creatures you control get +x/+x until end of turn, where x is the number of cards in your hand.` |  |
| Breaching Dragonstorm | `When ~ enters, exile cards from the top of your library until you exile a nonland card. you may cast it without paying its mana cost if that spell's mana value is <n> or less. if you don't, put that card into your hand.` |  |
| Broodcaller Scourge | `Whenever <n> or more dragons you control deal combat damage to a player, you may put a permanent card with mana value less than or equal to that damage from your hand onto the battlefield.` | Also uncovered in: Commander Cube |
| Deceptive Frostkite | `You may have ~ enter as a copy of a creature you control with power <n> or greater, except it's a dragon in addition to its other types and it has flying.` |  |
| Draconic Lore | `This spell costs <cost> less to cast if you control a dragon.` |  |
| Dragon Tempest | Compound gap — `Whenever a creature you control with flying enters, it gains haste until end of turn.`; `Whenever a dragon you control enters, it deals x damage to any target, where x is the number of dragons you control.` | Also uncovered in: Commander Cube |
| Dragon's Hoard | `Whenever a dragon you control enters, put a gold counter on ~.` | Also uncovered in: Commander Cube |
| Dragonlord Atarka | `When ~ enters, it deals <n> damage divided as you choose among any number of target creatures and/or planeswalkers your opponents control.` | Also uncovered in: Commander Cube |
| Eshki, Temur's Roar | `Whenever you cast a creature spell, put a +<n>/+<n> counter on ~. if that spell's power is <n> or greater, draw a card. if that spell's power is <n> or greater, ~ deals damage equal to ~'s power to each opponent.` |  |
| Gadrak, the Crown-Scourge | `At the beginning of your end step, create a treasure token for each nontoken creature that died this turn.` |  |
| Glorybringer | `You may exert ~ as it attacks. when you do, it deals <n> damage to target non-dragon creature an opponent controls.` | Also uncovered in: Commander Cube |
| Hammerhead Tyrant | `Whenever you cast a spell, return up to <n> target nonland permanent an opponent controls with mana value less than or equal to that spell's mana value to its owner's hand.` |  |
| Haven of the Spirit Dragon | `<cost>, <cost>, sacrifice ~: return target dragon creature card or ugin planeswalker card from your graveyard to your hand.` |  |
| Hellkite Courser | `When ~ enters, you may put a commander you own from the command zone onto the battlefield. it gains haste. return it to the command zone at the beginning of the next end step.` |  |
| Keiga, the Tide Star | `When ~ dies, gain control of target creature.` |  |
| Nesting Dragon | `Whenever a land you control enters, create a <n>/<n> red dragon egg creature token with defender and ~` |  |
| Nogi, Draco-Zealot | `Whenever ~ attacks, if you control <n> or more dragons, until end of turn, ~ becomes a dragon with base power and toughness <n>/<n> and gains flying.` |  |
| Opportunistic Dragon | `When ~ enters, choose target human or artifact an opponent controls. for as long as ~ remains on the battlefield, gain control of that permanent, it loses all abilities, and it can't attack or block.` |  |
| Parapet Thrasher | Compound gap — `Whenever <n> or more dragons you control deal combat damage to an opponent, choose <n> that hasn't been chosen this turn —`; `• ~ deals <n> damage to each other opponent.`; `• destroy target artifact that opponent controls.`; `• exile the top card of your library. you may play it this turn.` | Also uncovered in: Commander Cube |
| Reflections of Littjara | `Whenever you cast a spell of the chosen type, copy that spell.` |  |
| Sarkhan, Soul Aflame | `Whenever a dragon you control enters, you may have ~ become a copy of it until end of turn, except its name is ~ and it's legendary in addition to its other types.` |  |
| Scourge of the Throne | `Whenever ~ attacks for the first time each turn, if it's attacking the player with the most life or tied for most life, untap all attacking creatures. after this phase, there is an additional combat phase.` |  |
| Selvala's Stampede | `Starting with you, each player votes for wild or free. reveal cards from the top of your library until you reveal a creature card for each wild vote. put those creature cards onto the battlefield, then shuffle the rest into your library. you may put a permanent card from your hand onto the battlefield for each free vote.` |  |
| Skarrgan Hellkite | `<cost>: ~ deals <n> damage divided as you choose among <n> or <n> targets. activate only if ~ has a +<n>/+<n> counter on it.` |  |
| Steel Hellkite | `<cost>: destroy each nonland permanent with mana value x whose controller was dealt combat damage by ~ this turn. activate only once each turn.` |  |
| Stormbreath Dragon | `When ~ becomes monstrous, it deals damage to each opponent equal to the number of cards in that player's hand.` |  |
| Temple of the Dragon Queen | `As ~ enters, you may reveal a dragon card from your hand. ~ enters tapped unless you revealed a dragon card this way or you control a dragon.` |  |
| Temur Ascendancy | `Whenever a creature you control with power <n> or greater enters, you may draw a card.` |  |
| Territorial Hellkite | `At the beginning of combat on your turn, choose an opponent at random that ~ didn't attack during your last combat. ~ attacks that player this combat if able. if you can't choose an opponent this way, tap ~.` |  |
| Thunderbreak Regent | `Whenever a dragon you control becomes the target of a spell or ability an opponent controls, ~ deals <n> damage to that player.` | Also uncovered in: Commander Cube |
| Thundermane Dragon | `You may cast creature spells with power <n> or greater from the top of your library. if you cast a creature spell this way, it gains haste until end of turn.` |  |
| Ureni of the Unwritten | `Whenever ~ enters or attacks, look at the top <n> cards of your library. you may put a dragon creature card from among them onto the battlefield. put the rest on the bottom of your library in a random order.` | Also uncovered in: Commander Cube |
| Vengeful Ancestor | `Whenever a goaded creature attacks, it deals <n> damage to its controller.` |  |
| Whirlwing Stormbrood // Dynamic Soar | `You may cast sorcery spells and dragon spells as though they had flash.` |  |


### Turtle Power! - Teenage Mutant Ninja Turtles Commander Deck (34 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| April O'Neil, Live on the Scene | `Whenever a mutant, ninja, or turtle you control enters, investigate.` |  |
| Bebop, Skull & Crossbones | `Whenever ~ deals combat damage to a player, you may draw x cards, where x is the number of counters on ~. if you do, you lose x life.` |  |
| Big Apple, 3 a.m. | `<cost>, <cost>: create a <n>/<n> black rat creature token for each opponent you have.` | Also uncovered in: Wick Snail Boom |
| Big Mother Mouser | `When ~ dies, create a number of <n>/<n> colorless robot artifact creature tokens equal to the number of +<n>/+<n> counters on ~.` |  |
| Biogenic Ooze | `At the beginning of your end step, put a +<n>/+<n> counter on each ooze you control.` |  |
| Casey Jones, Back Alley Brute | `Whenever you put <n> or more +<n>/+<n> counters on a creature you control, ~ deals that much damage to target opponent.` |  |
| Coin of Mastery | `Each creature you control enters with an additional +<n>/+<n> counter on it for each mana from an artifact source spent to cast it.` |  |
| Continue? | `Choose up to <n> target creature cards in your graveyard that were put there from the battlefield this turn. return them to the battlefield.` |  |
| Dimension X Pizzasaur | `When ~ enters, put <n> +<n>/+<n> counters on target creature. when you do, destroy up to <n> target creature with mana value less than or equal to the number of counters among permanents you control.` |  |
| Donatello, the Brains | `If <n> or more tokens would be created under your control, those tokens plus a mutagen token are created instead.` |  |
| Double Jump // Flying Kick | `Put a flying counter on target creature you control. until end of turn, it has base power and toughness <n>/<n>.` |  |
| Electric Seaweed | `When ~ enters, until end of turn, whenever another creature dies, ~ deals <n> damage to each non-wall creature.` |  |
| Everything Pizza | `<cost>, <cost>, sacrifice ~: target player gains <n> life and draws a card. each of your opponents discards a card. ~ deals <n> damage to any target. put <n> +<n>/+<n> counters on up to <n> target creature.` |  |
| Exploding Barrel | `<cost>, <cost>, sacrifice ~: it deals <n> damage to target creature. this ability costs <cost> less to activate for each pressure counter on ~. activate only as a sorcery.` |  |
| Fast Forward | `This spell costs <cost> less to cast for each opponent you attacked this turn.` |  |
| Foot Chopper | `Whenever equipped creature deals combat damage to a player, you may sacrifice it. if you do, draw cards equal to its power.` |  |
| Game Over | `This spell costs <cost> less to cast if a player's life total is less than or equal to half their starting life total.` |  |
| Here Comes a New Hero! | `Target player draws x cards. create a token that's a copy of up to <n> target creature with mana value x or less.` |  |
| Heroes in a Half Shell | `Whenever <n> or more mutants, ninjas, and/or turtles you control deal combat damage to a player, put a +<n>/+<n> counter on each of those creatures and draw a card.` |  |
| Hidden Hideout | `<cost>, <cost>: target creature you control with a counter on it gains lifelink until end of turn.` |  |
| High Score | `At the beginning of your end step, draw a card if you control a creature with the greatest power among creatures on the battlefield.` |  |
| Irma, Part-Time Mutant | `At the beginning of combat on your turn, ~ becomes a copy of up to <n> other target creature you control, except her name is ~ and she has this ability. then put a +<n>/+<n> counter on her.` |  |
| Krang, the All-Powerful | `If a player drawing a card causes a triggered ability of a permanent you control to trigger, that ability triggers an additional time.` |  |
| Leonardo, the Balance | `Whenever a token you control enters, you may put a +<n>/+<n> counter on each creature you control. do this only once each turn.` |  |
| Michelangelo, the Heart | `Raid — at the beginning of your second main phase, if you attacked this turn, put a +<n>/+<n> counter on target creature and create a food token.` |  |
| Mole Module | `Whenever ~ deals combat damage to a player, mill <n> cards. you may put a permanent card from among them onto the battlefield.` |  |
| Ninja Pizza | `Foods you control have ~` |  |
| Ray Fillet, Wave Warrior | `Whenever a creature you control with a counter on it deals combat damage to a player, draw a card.` |  |
| Roadkill Rodney | `Whenever ~ deals combat damage to a player, create a mutagen token.` |  |
| Shellshock | `For each opponent, choose up to <n> target creature that player controls. ~ deals x damage to each of those creatures. you create a mutagen token for each creature dealt damage this way.` |  |
| Splinter, the Mentor | `Whenever ~ or another nontoken creature you control leaves the battlefield, create a mutagen token.` |  |
| Swift Demise | `~ deals <n> damage to target creature. then destroy each creature you don't control that was dealt damage this turn.` |  |
| Tempestra, Dame of Games | `<cost>, <cost>, sacrifice an artifact: create a token that's a copy of another target creature you control, except it isn't legendary. it gains haste. sacrifice it at the beginning of the next end step.` |  |
| Wave Goodbye | `Return each creature without a +<n>/+<n> counter on it to its owner's hand.` | Also uncovered in: Commander Cube |


### Wick Snail Boom (15 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Bespoke Battlegarb | `At the beginning of combat on your turn, if <n> or more nonland permanents entered the battlefield under your control this turn, attach ~ to up to <n> target creature you control.` |  |
| Bulk Up | `Double target creature's power until end of turn.` |  |
| Chameleon, Master of Disguise | `You may have ~ enter as a copy of a creature you control, except his name is ~.` |  |
| Crystal Shard | `<cost>, <cost> or <cost>, <cost>: return target creature to its owner's hand unless its controller pays <cost>.` |  |
| Demonspine Whip | `<cost>: equipped creature gets +x/+<n> until end of turn.` |  |
| Essence Flux | `Exile target creature you control, then return that card to the battlefield under its owner's control. if it's a spirit, put a +<n>/+<n> counter on it.` |  |
| Ghostly Flicker | `Exile <n> target artifacts, creatures, and/or lands you control, then return those cards to the battlefield under your control.` |  |
| Hide on the Ceiling | `Exile x target artifacts and/or creatures. return the exiled cards to the battlefield under their owners' control at the beginning of the next end step.` |  |
| Siren's Ruse | `Exile target creature you control, then return that card to the battlefield under its owner's control. if a pirate was exiled this way, draw a card.` |  |
| Teferi's Time Twist | `Exile target permanent you control. return that card to the battlefield under its owner's control at the beginning of the next end step. if it enters as a creature, it enters with an additional +<n>/+<n> counter on it.` | Also uncovered in: Commander Cube |
| Turn Inside Out | `Target creature gets +<n>/+<n> until end of turn. when it dies this turn, manifest dread.` |  |
| Unleash Fury | `Double the power of target creature until end of turn.` |  |
| Water Wings | `Target creature you control has base power and toughness <n>/<n> and gains flying and hexproof until end of turn.` |  |
| Wick, the Whorled Mind | Compound gap — `<cost>, sacrifice a snail: ~ deals damage equal to the sacrificed creature's power to each opponent. then draw cards equal to the sacrificed creature's power.`; `Whenever ~ or another rat you control enters, create a <n>/<n> black snail creature token if you don't control a snail. otherwise, put a +<n>/+<n> counter on a snail you control.` |  |
| Wings of Velis Vel | `Target creature has base power and toughness <n>/<n>, gains all creature types, and gains flying until end of turn.` |  |


### World Shaper - Edge of Eternities Commander Deck (16 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Aftermath Analyst | `<cost>, sacrifice ~: return all land cards from your graveyard to the battlefield tapped.` |  |
| Centaur Vinecrasher | Compound gap — `~ enters with a number of +<n>/+<n> counters on it equal to the number of land cards in all graveyards.`; `Whenever a land card is put into a graveyard from anywhere, you may pay <cost>. if you do, return this card from your graveyard to your hand.` |  |
| Escape to the Wilds | `Exile the top <n> cards of your library. you may play cards exiled this way until the end of your next turn.` |  |
| Eumidian Hatchery | `When ~ dies, for each hatchling counter on it, create a <n>/<n> black insect creature token with flying.` |  |
| Eumidian Wastewaker | `Whenever ~ attacks, you and defending player each discard a card or sacrifice a permanent. you draw a card for each land card put into a graveyard this way.` |  |
| Evendo Brushrazer | Compound gap — `During your turn, as long as you've sacrificed a nontoken permanent this turn, you may play cards exiled with ~.`; `Whenever you sacrifice a nontoken permanent, exile the top card of your library.` |  |
| Exploration Broodship | `Once during each of your turns, you may cast a permanent spell from your graveyard by sacrificing a land in addition to paying its other costs.` |  |
| Groundskeeper | `<cost>: return target basic land card from your graveyard to your hand.` |  |
| Hearthhull, the Worldseed | `Whenever you sacrifice a land, each opponent loses <n> life.` |  |
| Loamcrafter Faun | `When ~ enters, you may discard <n> or more land cards. when you do, return up to that many target nonland permanent cards from your graveyard to your hand.` |  |
| Moraug, Fury of Akoum | Compound gap — `Each creature you control gets +<n>/+<n> for each time it has attacked this turn.`; `Whenever a land you control enters, if it's your main phase, there's an additional combat phase after this phase. at the beginning of that combat, untap all creatures you control.` |  |
| Planetary Annihilation | `Each player chooses <n> lands they control, then sacrifices the rest. ~ deals <n> damage to each creature.` |  |
| Scouring Swarm | `Whenever you sacrifice a land, create a tapped token that's a copy of ~ if <n> or more land cards are in your graveyard. otherwise, create a tapped <n>/<n> black insect creature token with flying.` |  |
| Splendid Reclamation | `Return all land cards from your graveyard to the battlefield tapped.` |  |
| The Gitrog Monster | `Whenever <n> or more land cards are put into your graveyard from anywhere, draw a card.` |  |
| Worldsoul's Rage | `~ deals x damage to any target. put up to x land cards from your hand and/or graveyard onto the battlefield tapped.` |  |


### yshtola (18 cards)

| Card | Gap | Notes |
| --- | --- | --- |
| Alela, Cunning Conqueror | Compound gap — `Whenever <n> or more faeries you control deal combat damage to a player, goad target creature that player controls.`; `Whenever you cast your first spell during each opponent's turn, create a <n>/<n> black faerie rogue creature token with flying.` |  |
| Baral, Chief of Compliance | `Whenever a spell or ability you control counters a spell, you may draw a card. if you do, discard a card.` | Also uncovered in: Commander Cube |
| Battlefield Thaumaturge | `Each instant and sorcery spell you cast costs <cost> less to cast for each creature it targets.` |  |
| Bloodchief Ascension | Compound gap — `At the beginning of each end step, if an opponent lost <n> or more life this turn, you may put a quest counter on ~.`; `Whenever a card is put into an opponent's graveyard from anywhere, if ~ has <n> or more quest counters on it, you may have that player lose <n> life. if you do, you gain <n> life.` |  |
| Case of the Ransacked Lab | `To solve — you've cast <n> or more instant and sorcery spells this turn.` |  |
| Chill to the Bone | `Destroy target nonsnow creature.` |  |
| Defiler of Dreams | Compound gap — `As an additional cost to cast blue permanent spells, you may pay <n> life. those spells cost <cost> less to cast if you paid life this way. this effect reduces only the amount of blue mana you pay.`; `Whenever you cast a blue permanent spell, draw a card.` |  |
| Dragon's Prey | `This spell costs <cost> more to cast if it targets a dragon.` |  |
| Eyeblight's Ending | `Destroy target non-elf creature.` |  |
| Faebloom Trick | `Create <n> <n>/<n> blue faerie creature tokens with flying. when you do, tap target creature an opponent controls.` |  |
| Hibernation | `Return all green permanents to their owners' hands.` |  |
| Leadership Vacuum | `Target player returns each commander they control from the battlefield to the command zone.` |  |
| Lookout's Dispersal | `This spell costs <cost> less to cast if you control a pirate.` |  |
| Nocturnal Hunger | `Destroy target creature. if the gift wasn't promised, you lose <n> life.` |  |
| Rend Flesh | `Destroy target non-spirit creature.` |  |
| Stormscape Familiar | `White spells and black spells you cast cost <cost> less to cast.` |  |
| Sygg, River Cutthroat | `At the beginning of each end step, if an opponent lost <n> or more life this turn, you may draw a card.` |  |
| Unwind | `Counter target noncreature spell. untap up to <n> lands.` |  |
