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
| `ANA` | Deck analysis — UC2 |
| `BUG` | Bugs — a shipped behaviour that is wrong (a wrong-but-`MODELED` claim, a silently dropped clause); not missing coverage |
| `REL` | Release & deployment — steps done when cutting a release (version pins, locks, packaging), not during development |

---

## ENG — Game engine

- **ENG-64 · Trigger-subject reference for group effects.** RULE 603.2 / 608.2c: mass destroy / tap / sacrifice resolve their group against the effect's source (`life_sacrifice._mass_group_objects` -> `_group_objects(src=source)`), so "... that shares a color with it" / "with the same name as that creature" under a trigger compares with the source, not the trigger subject (PAR-285 M15: a parser claim destroyed nothing for Spreading Plague). Add a `reference: trigger_subject` on group effects; `named_as_reference` / `shares_*_with_reference` filters already exist. Unlocks Spreading Plague; also needed by Dual Nature, Eye of Singularity, Faces of the Past, Martyr's Bond (`shares_card_type` key) and Legion's End, which each keep a second gap.

## PAR — Parser

Fragment-axis tickets carry `touched` / `only` counts from a `find-fragments`
discovery: cards containing the family / cards whose every open sentence belongs to
it; overlapping upper bounds, not guaranteed unlocks. Before implementation,
re-scan and verify subfamilies and remaining blockers with `parser_probe blocked`;
before closure, diff full-pool specs for zero losses, execute newly claimed cards,
run the backend suite including full-cache, and re-scan with `find-fragments`.

**Completeness rule.** PAR-281–311 together cover the whole open card cache, not only
Commander: the v912 full-cache scan (2026-11-16) has 8,875 open cards / 13,777 sentences, each
assigned to exactly one package. `find_fragments.py --all-cards --axes` writes the
card → sentence → package table and fails if any open card is unassigned; re-run it after every
closed ticket and after pool updates, and move newly open cards into a ticket at once. Counts
below are `sentences / touched / only` from that scan; the quoted package name is the key in the
assignment table. Groups under 3 cards after two passes go to `singletons.md`. Done means zero
open cards except `NEVER_SUPPORTED` and the parked packages named in `DEFERRED.md` (the scan lists them as `GEPARKT …`). A family ticket files its own MEC ticket when a grep and
`engine_bench.py` confirm a missing primitive.

Single-axis packages (one missing building block; the rest of the sentence already claims):

- **PAR-286 · Trigger and cost heads.** `P1-D Trigger-/Kostenköpfe` 383 / 757 / 161; 374 further sentences need a head and another package. PAR-284 residue: P1-B amount sentences whose only open part is the head: `when you cycle this card` (Gempalm Incinerator), `whenever enchanted creature attacks` (Thunderous Might), `whenever equipped creature attacks alone` (Sigil of Valor), `whenever the final chapter ability of a saga you control resolves/triggers` (Narci, also Historian's Boon, Tom Bombadil); their amount phrases already parse. PAR-284 close: Vivien's Stampede (delayed head "at the beginning of the next main phase this turn"). PAR-285 close: Lobelia Sackville-Baggins, Sapphire Charm, The Spear of Bashenga (heads; their object filters parse).
- **PAR-287 · Cross-sentence referents.** `P1-E Rückbezug` 368 / 344 / 78: `it`, `that card`, `that many`, `the exiled card`, sentences that claim only with their predecessor. PAR-283 residue: "if you do / you don't / you can't / they do" (~200 sentences) is not a missing predicate; the antecedent clause stays open, so the `if_you_do_from` outcome chain needs widening per antecedent verb (Akuta, Act of Authority, Egon). PAR-284 residue: Bounding Felidar: `you gain 1 life for each of those creatures` counts the creatures of the previous sentence (back-reference count).
- **PAR-288 · Small modifiers.** `P1-F Kleinmodifikatoren` 64 / 63 / 36: `at random`, `instead`, `up to N`, order, duration.

Operation families (no single-axis repair; sub-cluster by slot before building):

- **PAR-289 · Continuous statics.** `P2 Statische Dauereffekte` 858 / 818 / 506.
- **PAR-290 · Restrictions.** `P2 Einschränkungen` 680 / 649 / 372.
- **PAR-291 · Player-scoped actions.** `P2 Spielerbezogene Aktionen` 822 / 746 / 320. Remaining cross-dimension pools ("island or blue permanent") and "exiles cards from the top until ..." plus cast riders stay here. PAR-315/317 residue: multi-player scopes (Raging River, Stand or Fall, Butcher Orgg; "you and defending player each": Cait, The River Warlock).
- **PAR-292 · Library inspection and search.** `P2 Bibliothek` 1,049 / 802 / 319. Dynamic search qualities ("with the same name as <ref>", "mana value equal to <amount>", 18 cards) need only a dynamic bound in `filter_slots.quality_criteria` once PAR-284 supplies the amount. PAR-284 close: Demonlord Belzenlok (repeat-until loop with a put-into-hand-this-way tally). PAR-285 close: Alpine Houndmaster, Assembly Hall, Disciple of Deceit, Infernal Tutor, March of Burgeoning Life, Night Dealings, Pattern Matcher, Repurposing Bay, Ringsight, Savage Order, Uncage the Menagerie, Wild Pair (search criteria beyond the shared quality / mana-value slots).
- **PAR-293 · P/T, keyword grants and characteristics.** `P2 P/T und Keyword-Vergabe` 584 / 562 / 306; `P2 Charakteristik` 146 / 143 / 66. PAR-285 close (mis-scanned as object filters): "becomes a N/N <type> with <quality>" / base P/T: Animate Spell, Ascendant Spirit, Cosmium Confluence, Domesticated Watercourse, Figure of Fable, Fractalize, Gideon Champion of Justice, Opal Guardian, Opal Titan, Optimus Prime Inspiring Leader, Veiled Sentry, Woodcaller Automaton.
- **PAR-294 · Replacement effects.** `P2 Ersatzeffekte` 558 / 550 / 302. PAR-284 close: Unbreathing Horde (prevent damage and remove a +1/+1 counter instead; the entry count parses).
- **PAR-295 · Graveyard returns and zone moves.** `P2 Friedhof` 425 / 415 / 239; `P2 Zonenwechsel` 236 / 221 / 76. "Return target <type> card with mana value N or less from your graveyard" (10 cards, e.g. Can't Stay Away, Orzhov Charm) needs a mana-value key on graveyard target kinds plus one `filter_slots` row. PAR-284 close: Paradoxical Outcome, Revival Experiment (zone-move producers feeding a returned-this-way tally).
- **PAR-296 · Damage.** `P2 Schaden` 400 / 383 / 233.
- **PAR-297 · Tokens and copies.** `P2 Spielsteine` 409 / 379 / 206; `P2 Kopie` 215 / 204 / 53. PAR-285 close: named tokens and token riders: Basri Ket, Bottle-Cap Blast, Brimaz King of Oreskos, Commodore Guff, Dora Milaje Elite, Emrakul and Chatterfang, Forbidden Friendship, Giant Caterpillar, Inquisitorial Rosette, Koma Cosmos Serpent, Koma World-Eater, Nahiri the Unforgiving, Parhelion II, Rukh Egg, Sigiled Sword of Valeron, Tamiyo Compleated Sage, Transluminant, Urza's Hot Dog Stand, Wurmcoil Engine, Wurmcoil Larva ("that's attacking" rider: Brimaz, Inquisitorial Rosette, Sigiled Sword, Parhelion II; two different tokens in one create: Forbidden Friendship, Wurmcoil Engine, Wurmcoil Larva).
- **PAR-298 · Choices.** `P2 Wahl` 998 / 854 / 203: choose, vote, random, naming, piles, bidding. ENG-62 residue: Temporal Firestorm's non-targeted "choose up to X creatures and/or planeswalkers you control ... phase out". PAR-284 residue: vote tallies (Círdan the Shipwright `for each vote they received`, Truth or Consequences `for each consequences vote`, Messenger Jays `feather / quill vote`, Erestor of the Council `opponents who voted for a choice you didn't vote for`) and chosen-card-type reveals (Blood Oath, Fertile Imagination `cards of the chosen type revealed this way`); the amount follows the vote / choice record. PAR-284 close: Intrude on the Mind (pile separation is not a mill), Messenger Jays (vote tally, drawn this way). PAR-285 close: Extinction Event, Mutinous Massacre, Power of Persuasion, Rivals' Duel, Saga of Krark Losing His Thumb, Split the Spoils, Thanos the Mad Titan, V.A.T.S., Wild Swing.
- **PAR-299 · Cast permissions and alternative costs.** `P2 Zauber-Erlaubnis und Alternativkosten` 618 / 595 / 193. PAR-283 residue: Trap alt-cost conditions now take the shared vocabulary; still open are Ravenous Trap ("put into a graveyard from anywhere" tally incl. resolved spells), Cobra Trap (destroyed by an opponent's spell/ability) and Summoning Trap (countered by an opponent) tallies, and Refraction Trap's body. PAR-284 residue: Winged Portent: cleave bracket text `[with flying]` inside a for-each count. PAR-284 close: Dragon Man, Reformed Robot (graveyard cast with an additional discard), Notorious Throng (prowl paid + extra turn); amounts parse. PAR-285 close: Kaervek the Punisher (exile, copy, may cast; lose 2 life if you do), Lara Croft Tomb Raider (discovery-counter play permission), Massimo the Magician (copy through a granted ability); their graveyard picks parse.
- **PAR-300 · Counters.** `P2 Marken` 403 / 374 / 190. PAR-284 close: Cleopatra, Exiled Pharaoh (counter on each of up to two other target legendary creatures). PAR-285 close: Cleopatra Exiled Pharaoh, Katsumasa the Animator, Master's Guidance, Rhino Terrible Trampler.
- **PAR-301 · Cost modifiers and payments.** `P2 Kostenmodifikatoren und Zusatzkosten` 324 / 306 / 172; `P2 Optionale Zahlung` 99 / 98 / 15. PAR-284 residue: scaled payments: `sacrifice ~ unless you pay {1} for each <count>` (Extravagant Spirit, Megatherium, Phantasmal Sphere, Cyclone), `equip - pay 1 life for each card in your hand` (Hand of Vecna); reflexive `when you do` after an optional payment feeding a count (Invisible Woman).
- **PAR-302 · As-enters and enters-with.** `P2 As-enters und Enters-with` 333 / 307 / 144. PAR-314 residue: "As ~ enters, <action>" (119 cards, 32 solo at v937, e.g. Urborg Lhurgoyf's "mill 3 cards for each time it was kicked", Heightened Awareness's "discard your hand") needs an as-enters action form that applies as a replacement (RULE 614.1c), never via the stack; amounts like `source_kicker_count` already bind.
- **PAR-303 · Exile linkage.** `P2 Exil und Bezug auf exilierte Karten` 382 / 352 / 113. "Exile all [quality] cards from <hand/graveyard>" needs a new zone-exile effect (17 cards, e.g. Identity Crisis, Serum Powder, Hex Magic). PAR-285 close: Ashiok Nightmare Weaver, Bottled Cloister, Duplicity, Epochrasite, Evelyn the Covetous, Haunting Echoes, Ice Cauldron, Identity Crisis, Idol of Endurance, Ignorant Bliss, Leonardo da Vinci, Moonring Mirror, Power Pack, Saprazzan Bailiff, Semblance Anvil, The Animus ("becomes a copy of a card in exile"), Thought Distortion, Tinybones Bauble Burglar, Ultimate Nullification, Wizard's Spellbook, Worldfire, Wormfang Behemoth.
- **PAR-304 · Attachment and control.** `P2 Anlegen` 190 / 176 / 111; `P2 Kontrolle und Tausch` 102 / 101 / 31. PAR-284 residue: Coveted Falcon: `for each 1 they gained control of this way` tally after the control-exchange clause.
- **PAR-305 · Combat.** `P2 Kampf` 200 / 190 / 100.
- **PAR-306 · Life, draw and discard.** `P2 Leben` 189 / 179 / 78; `P2 Ziehen/Abwerfen` 149 / 146 / 56. PAR-284 residue: discard producers that feed a `this way` tally: `discard your hand` (Balin, Loremaster) and `discard any number of cards` (Rites of Refusal `{3} for each card discarded this way`). PAR-284 close: windowed `drawn this way` pool for a draw producer (Ancient Excavation, Read the Runes; 5 more wait on other clauses).
- **PAR-307 · Mana and energy.** `P2 Mana und Energie` 232 / 210 / 70. PAR-284 residue: `add X mana of any 1 color / any combination of colors / {R} and/or {G}, where X is <count>` host (Klauth, Sanctum of Fruitful Harvest, Xenagos the Reveler, Plasm Capture delayed, Metamorphosis): the amount phrases parse, the `add_mana` any-colour host does not bind a where-X.
- **PAR-308 · Stack interaction and text changes.** `P2 Stapel` 93 / 93 / 65; `P2 Textänderung` 14 / 13 / 10. PAR-284 residue: `counter all spells` producers that feed `for each spell (and ability) countered this way` (Glen Elendra's Answer, Swift Silence). PAR-285 close: Ayesha Tanaka, Frontline Medic, Louisoix's Sacrifice, Mindreaver, Nimble Obstructionist, Ouphe Vandals, The Peregrine Dynamo (counter target ability / spell variants).
- **PAR-309 · Small families.** `P2 Opfern/Zerstören` 170 / 165 / 70; `P2 Zug und Phase` 56 / 56 / 31; `P2 Keyword-Aktionen` 45 / 43 / 18; `P2 Face-down/Transform` 34 / 32 / 14; `P2 Spielausgang und Sonderregeln` 59 / 59 / 13; `P2 Tappen/Enttappen` 51 / 48 / 11; `P2 Phasing` 11 / 11 / 4; `P2 Würfel und Münze` 21 / 17 / 4; `P2 Zähl- und Prozessanweisungen` 22 / 22 / 4; `P2 Bedingte Anweisungen` 28 / 28 / 3; `P2 Tabellen- und Variantenzeilen` 31 / 13 / 3. PAR-284 residue: dice / coin tallies: `roll a d20 for each player being attacked, ignore all but the highest` (Iron Mastiff), `take an extra turn for each coin that comes up heads` (Ral Zarek). PAR-284 close: Out of Time (phased-out-this-way pool; check the phasing event first), Reign of Terror (destroy-all-X-or-all-Y producer, then died this way).

## MEC — Game mechanic

- **MEC-144 · Sideboards as a feature for non-Commander formats.** Sideboard use (cards outside the game, RULE 400.11, 100.4) as a deliberate per-format feature; Commander games stay without one (RULE 903.5f). Scope (per-format rules, matches and sideboarding between games, UI) to be refined before starting. Base: `game/sideboard.py`, `Player.sideboard`.
- **MEC-145 · Recorded referents of cost and effect objects (discarded, exiled, tapped, revealed, sacrificed sum).** RULE 608.2h last-known information for what a cost or effect moved: generalize the `sacrificed_cost_*` stamps (`activation_mixin._record_sacrifice_cost`, `casting_mixin` additional cost) to discard, exile (graveyard / top-of-library / linked exile), tap and reveal costs and to the effect-produced single referent (`the discarded / exiled / returned card's mana value, power, toughness, number of card types`, `the creature tapped this way`, total power of all sacrificed creatures), read by `continuous.count_selector` / `effect_amounts` so the parser can bind `where X is the <noun>'s <characteristic>`. Today only the sacrifice stamps and `last_cost_exiled_object_mv` (Food Chain) exist; `discarded_cost_card_types` / `_words` record types only (grep + `engine_bench primitives` confirmed no mana-value / power record for discard, graveyard-exile, tap or reveal costs). Unlocks (21 in P1-B): Slumbering Tora, Volrath the Fallen, Necropolis, Phyrexian Devourer, Impelled Giant, Keldon Battlewagon, Disaster Radius, Induce Despair, Draconic Intervention, Flesh // Blood, Bishop of Binding, Redemptor Dreadnought, Spellbound Dragon, Mount Velus Manticore, Foul Renewal, Ruinous Intrusion, Venom, Shadowheart, Minsc & Boo, Sword of the Ages, Vicious Betrayal. Broad grouping: before starting, check each effect-produced referent (Spellbound Dragon, Mount Velus Manticore, Foul Renewal, Ruinous Intrusion, Venom, Minsc & Boo) against existing primitives. PAR-284 close: amassed-Army referent (RULE 701.48; `AmassEffect` records the Army only when it creates one): Foray of Orcs, Surrounded by Orcs, Grishnákh Brash Instigator, Goblin Plate Mail. PAR-285 close: Arcbond, Argentum Masticore, Calamity of the Titans, Endemic Plague, Fatal Grudge (shares a card type with the sacrificed permanent), Kogla and Yidaro, Mandate of Abaddon, Nahiri's Sacrifice (X = sacrificed mana value), Nihiloor, Public Execution, Resplendent Marshal, Sanguine Praetor, Saruman of Many Colors, Simic Manipulator, Soundwave, Sundering Archaic, Unleash the Inferno, Void, Wrath of the Skies (some with PAR-287 back-references).
- **MEC-146 · Pay-any-amount choices with a recorded total.** RULE 118.1 / 601.2: `starting with you, each player may pay any amount of mana / life / {E}` (and `discard any number of cards`) as one resolution step that records each player's paid amount and a combined total for the rest of the resolution (`the total amount of mana paid this way`, `for each 1 life they paid this way`, `{1} for each {E} paid this way`). Only the single-player `Leyline Tyrant` hand-authored shape exists (grep `pay any amount`: `rules/misc_helpers.py` x-colour announcements only). Unlocks 6 in P1-B: Alliance of Arms, Mana-Charged Dragon, Minds Aglow, Shared Trauma, Aether Spike, Plague of Vermin (repeat-until-nobody-pays loop).
- **MEC-147 · Devour: generic keyword binding and a devoured-creature record.** RULE 702.82: `DevourEntryEffect` (`game/effects/devour_entry.py`, RULE 702.82a sacrifice before entry counters) exists but only Ravenous Gigantotherium binds it by hand; the `Devour N` keyword is not bound generically, and nothing records which creatures were devoured. Bind the keyword for every card, and keep a per-object record of the devoured creatures (count, last-known characteristics) readable as `for each creature it devoured` / `if it devoured a creature`. Unlocks 3 P1-B cards: Marrow Chomper, Skullmulcher, Tar Fiend; fixes BUG-71.
- **MEC-148 · Per-object mutate count.** RULE 702.140: record how many times a permanent has mutated (`GameObject` counter bumped by `mutate_onto`, kept across the merged pile, reset by RULE 400.7 on zone change) and expose it as the count selector `times_mutated` (`EventType.MUTATES` exists, no count; grep `times_mutated` / `mutate_count`: none). Unlocks 4 P1-B cards: Archipelagore, Huntmaster Liger, Insatiable Hemophage, Porcuparrot.
- **MEC-149 · Mana spent to cast, split by the paying source's land subtype.** RULE 601.2h: the payment records amount / colors / snow / Treasure but not which land subtypes paid (`casting_mixin` `source_mana_spent` stamp); add `mana_spent_to_cast_by_source_subtype` so `mana from a Cave / Desert spent to cast it` can be counted. Unlocks Bat Colony in P1-B (Cataclysmic Prospecting shares it outside P1-B); 2 cards, filed as a MEC because the missing piece is engine state and the parser row is trivial.
- **MEC-150 · Per-player put from hand onto the battlefield.** RULE 101.4 / 110.2: "each player/opponent may put <types> card(s) from their hand onto the battlefield" — every chosen player picks from their own hand in APNAP order and controls what enters. `PutFromHandOntoBattlefieldEffect` (`game/effects/library.py`) acts only for the effect's controller (grep + PAR-285 M10 sizing). Step 1, player scope: Show and Tell, Hunted Wumpus, Iwamori of the Open Fist, Charmed Griffin, Tempting Wurm (+ any-number count). Step 2, repeat-until-nobody-puts loop and a per-player did-put flag: Eureka, Hypergenesis, Kynaios and Tiro of Meletis, Anax and Cymede & Kynaios and Tiro. Then The Great Aurora, Worlds Within Worlds. The clause is the only open part of all 11 (`parser_probe blocked`). PAR-285 close: also Kastral the Windcrested, Thran Temporal Gateway.

## PLR — Player management

- **PLR-9 · User accounts (umbrella).** Split into PLR-9a–e, released in that order; enforcement and
  client updates ship together at the PLR-9e cutover. Design, decisions and verification gates: [plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md).
  Coordinate asset ownership with PLR-16 (hard gate for the cutover) and operator authorization with PLR-17.
- **PLR-9a · Run modes, account storage and authentication.** Default LAN mode accepting only the host's
  own IP ranges (VPN interfaces included), `--online` (HTTPS-only secure mode), `--localdev` (loopback,
  default-localuser that can log out and be replaced by a player login); separate `accounts.db` with
  versioned migrations; password hashing (Argon2id, or stdlib scrypt if no new dependency is wanted —
  decide with measurements); sessions, `/api/auth`, CSRF/Origin extension of `request_guard.py`,
  throttling; unique login and display names; login/signup UI slice; update the `CLAUDE.md`/OPERATIONS startup directive.
- **PLR-9b · Deck and session ownership.** Deck scope (`global`/`private`/`unassigned`) and owner in SQL;
  authorization through every `get_deck` consumer; private Goldfisch/Solo/Replay session ownership;
  operator migration command (bulk "assign to account" mode); needs PLR-9a.
- **PLR-9c · Multiplayer identity and reconnect.** Bind `LobbyPlayer` to accounts, authenticated WS, remove
  name/client-token/secret fallbacks, single-session lock (second tab with the same account is blocked
  with "Blockiert aufgrund paralleler Session"); needs PLR-9a/9b.
- **PLR-9d · Administration.** Separate admin entrypoint (`/api/admin`, dedicated host, MFA before remote
  use): player list/create/disable/delete and session revoke (no admin-initiated password reset), global-deck
  CRUD, allowlisted DB-update jobs, audit log; needs PLR-9a/9b, enforcement of update routes via PLR-17.
- **PLR-9e · Data protection and cutover.** Encryption at rest and backups (decide SQLCipher vs encrypted
  volume first), key handling, security-event logging, `no-store` headers, requirement-to-test mapping,
  coordinated migration/cutover, docs and Done entries; closes PLR-9.
- **PLR-16 · Bind player assets to an owner instead of the free-text name.** Sleeves,
  token art and favorites (`services/player_assets.py`) are keyed by the freely chosen
  name: anyone can upload or delete under any name (`/api/players/{name}/…`). The sweeper
  also deletes a name's uploads when a foreign token expires (`delete_all_for_player(name)`
  in `api/multiplayer_ws.sweep_once`), which lets an attacker who uses the victim's name with
  their own token wipe the victim's art. Tasks: until PLR-9 lands, accept writes/deletes only
  with the lobby secret (`LobbyPlayer.secret`) of the owning player; purge only uploads the expired token created
  itself (store the token/owner per row); after PLR-9a–c, migrate to `account_id`.
- **PLR-17 · Protect admin/server routes.** Anyone who can reach the port can change or clear
  the LLM settings (`PUT /api/llm/settings`), burn LLM quota (`/api/llm/test`, narrative
  analysis, LLM bots) and start the card-pool/combo updates (`/api/cards/update`,
  `/api/combos/update`). Tasks: authorize allowlisted database refresh/update routes
  for authenticated admin accounts only; player accounts must be denied even via
  direct API calls. LLM settings/tests and other server operations remain OS-operator
  only, outside the admin account permission set. Loopback alone does not authorize
  a browser request. Coordinate separate admin identities/UI with PLR-9d; tests.

## VIS — Visuals

- **VIS-15 · Deck building tool.** Add a dedicated navigation section for creating and editing
  Commander decks with card search/filtering, commander selection, card quantities, live deck
  metrics, server-authoritative legality feedback and saved drafts/decks for analysis and play;
  scope and acceptance criteria: [project goal](../requirements/02_MVP_USECASES_REVISED.md#deck-building-tool).
- **VIS-8 · Keyboard shortcuts.** docs/05 PART 9 (Space/Enter/E for pass and yield already exist).
- **VIS-9 · Accessibility** — alt-text on cards, tab navigation,
  high-contrast mode. docs/05 PART 10.
- **VIS-10 · Responsive/mobile layout** — only checked at desktop width.
- **VIS-21 · Hard-coded German picker labels.** `gameBoardView.js` passes literal German labels to the tap-cost
  pickers ('zu tappende Kreatur', 'zu tappende bleibende Karte', ~lines 3222, 3355, 3495), so the English UI
  shows German. Move them into `locales/de|en/board.js` keys and sweep the board for other literal UI text.

## DB — Database

> **Gotcha:** adding a field to `Card` changes the schema hash, and
> `CardDatabase` wipes the whole app cache on mismatch. Recover offline with
> `python scripts/import_bulk.py --reseed-only` (rebuilds ~34k rows from
> `RawCardStore`). A targeted per-field backfill is never the right answer —
> the wipe is all-or-nothing.

## ANA — Deck analysis

- **ANA-5 · Automatic missing-card discovery from saved decks.** After a permitted successful create/import
  or card-list-changing save (metadata-only edits reuse results), enqueue a durable, retryable, coalesced
  job that evaluates every distinct card with the authoritative coverage verdict (`api/saved_decks.py`
  parser version + catalogue signature). Persist deduplicated gap candidates by canonical card identity with
  versioned evidence in a server-data queue under `MTG_DATA_DIR`; keep UNMODELED, permanent Unsupported and
  unresolved card/cache/network errors apart; no source deck id, name, owner or count in the shared queue.
  Runtime stores gap evidence only; classification (singleton vs shared cluster) runs in a developer-side sync
  command that reuses `singleton-sweeper`/`find-fragments` admission rules and merges confirmed singletons
  into `singletons.md` idempotently. Re-evaluate on parser/catalogue/card-pool updates; jobs bind to deck
  version so stale results cannot overwrite newer ones. Show missing cards and status in the UI after saving.
  Needs a job runner (none exists; DYNAMIC_ANALYSIS workers are in-process). Works before PLR-9; under
  accounts it applies to player and admin saves alike. Tests: dedup, restart-survival, stale-job, no provenance
  leak via API/logs, idempotent Markdown sync.

## BUG — Bugs

- **BUG-69 · Planar deck can contain a joke "Phenome-nom" card (flaky `test_a_planechase_game_starts_with_a_face_up_plane`).** `VariantCardDatabase` sorts planar cards by layout, so the silver-border "That's Enough Slices" (type line "Phenome-nom") can be dealt as the starting plane. The full-cache test then fails at random. Reproduce by seeding `make_engine("planechase")` until that card comes up. Fix: keep only real Plane and Phenomenon type lines out of tournament-legal or black-border printings, or decide that joke cards are deliberately allowed and relax the test.

- **BUG-71 · Hand-authored Devour cards drop their Devour.** Mycoloth and Ribtruss Roaster are authored without the `Devour N` entry (`card_catalogue/m/mycoloth.py`, `r/ribtruss_roaster.py`), so they enter without the optional sacrifice and its +1/+1 counters (RULE 702.82a) while claimed as covered. Fix with MEC-147's generic Devour binding, or add `devour_entry` to both entries as Ravenous Gigantotherium does.

- **BUG-72 · Parsed "target opponent" can target its own controller.** `parser/oracle/catalogue/subgrammars.py` maps `target opponent` to the plain `"player"` target kind (`resolve_target_kind`), so rows that use it, e.g. `effect_rows/damage_copy.py` ("~ deals 3 damage to target opponent"), offer and accept the controller as a target (RULE 115.1 / 102.3: an opponent is another player). Reproduced on Bulwark's upkeep trigger in a 2-player game: the `trigger_target` choice lists p1 and p2 and `resolve_choice("p1")` is accepted. `edicts.py`, `counters_blocking.py` and `destroy_exile_counter.py` already emit `"opponent"`. Fix: map the row to `"opponent"`, size the reshaped MODELED specs with a version-masked full-pool diff, and add a regression test that the controller is not a legal pick.

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock.** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
