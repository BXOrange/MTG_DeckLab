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

**Star Trek (TRK + TRC) scan, 2026-11-10:** CR 20261106, PARSER_VERSION 870, 647 unique Oracle cards in the two sets, 436 covered (405 `MODELED` + 31 `AUTHORED`, 67.4 %), 211 open. Every open card is assigned below: ENG/MEC (rules primitives), PAR (shared shapes) or the Star Trek section of [singletons.md](singletons.md). Counts are `touched` upper bounds; re-verify each family with `parser_probe blocked` before starting. Done when all 647 are covered (re-run `scripts/coverage_report.py`) **and** a real-engine cast of every newly covered card passes.

- **ENG-55 · Attacking-entry replacement and attack-target retention (RULE 508.4, 508.4e).** CR 20261106 adds 508.4e: if several effects put a creature onto the battlefield attacking, each effect's own "attacking player/planeswalker/battle" specification still applies whatever the order. Needed: (1) a replacement effect "if a creature you control would enter while you control an attacking creature, instead it enters tapped and attacking" (Kira Nerys, Firebrand; the first replacement that adds attacking status), with the attack-target chosen per 508.4 and kept when other effects also place it attacking (Rite of Ascension's tapped-and-attacking tokens, PAR-152's placed-attacker path); (2) "reselect which player or permanent that creature is attacking" for attackers already declared (Tuvok, Chief Tactical Officer, entering during the declare attackers step; reuse the retarget plumbing behind Misleading Signpost). Cards: Kira Nerys, Firebrand, Tuvok, Chief Tactical Officer (2). Tests: stacked attacking-entry effects in both orders, planeswalker/battle targets, a defender who left the game (508.4a).
- **ENG-56 · Off-battlefield power/toughness of striated cards (RULE 208.3, changed 2026-11-06).** A noncreature object off the battlefield now has power/toughness only if the printed P/T is not part of one of its abilities; Spacecraft (and Vehicle-style striated text boxes) keep their P/T inside the station ability, so a Spacecraft card in hand, graveyard, library or on the stack has none. Audit every reader of printed `power`/`toughness` on cards outside the battlefield (`models/cards/card_query.py`, targeting and search filters, "creature card with power N or less", mana-value-style comparisons, the wire view) and fix the Spacecraft/Station case; Vehicles keep their printed P/T off the battlefield. Tests: a Spacecraft in graveyard/hand does not match a power filter, becoming a creature on the battlefield still works (RULE 722.2 station thresholds), Vehicles unchanged.
- **ENG-57 · CR 20261106 adoption sweep (small deltas).** The ruleset update (effective 2026-11-06) also changed rules the engine implements; verify each against the code and either fix or record "already compliant": 122.1g (a **non-Siege** battle with 0 defense is put into the graveyard even when it is the source of a triggered ability that has not left the stack; only Siege battles keep that exception; check `_sba_collect_battle_zero_defense`), 614.13a/b (an "enters" replacement cannot choose objects entering or leaving any zone at the same time; cards milled or exiled from the library by another replacement while applying it are excluded), 701.27 and 701.28 (re-lettered and consolidated from 712: transforming/converting makes no new object, "can't transform" also stops converting, 701.27h-j define "transformed permanent" and send an instant/sorcery back face that would enter transformed to the graveyard; confirm no behavior change), 712.x restructuring (meld cards moved to new RULE 713; 20260807 numbers 712.4/712.5/712.21 now live in 713), 903.5f (Commander games do not use sideboards; check `game_session` sideboard handling in Commander seats), 111.10x and 205.3g (Heartwood token and artifact type), and the Werewolf Pack Leader Oracle update (the activated ability now makes it a Werewolf, losing other creature types).

## PAR — Parser

Fragment-axis tickets carry `touched` / `only` counts from a `find-fragments`
discovery: cards containing the family / cards whose every open sentence belongs to
it; overlapping upper bounds, not guaranteed unlocks. Before implementation,
re-scan and verify subfamilies and remaining blockers with `parser_probe blocked`;
before closure, diff full-pool specs for zero losses, execute newly claimed cards,
run the backend suite including full-cache, and re-scan with `find-fragments`.
Latest scan: 2026-11-05, v830, 8,246 open Commander cards / 12,170 fragments.

Body/sentence tickets (PAR-237..242) from the same scan's template ranking (`touched` / `solo`; per-template upper bounds):

- **PAR-258 · "Differently named lands you control" as a dynamic amount (Strange new worlds).** Only the cost-reduction and CDA slots read `distinct: 'name'` today; the open cards use it elsewhere: gain life equal to, draw X, create X tokens, exile the top X, +X/+0 or -X/-X where X is the count, `{N}: ... this ability costs {X} less to activate` (grep finds no activated-ability cost reduction yet; verify), reveal-top-X and "mana value N or less where N is the count", "put X additional counters", and conditions "if you control N or more differently named lands". Cards: Astute Terraformer, Branching Timeline, Chief Montgomery Scott, Christine Chapel, Combat Medic, Commander Spock, Deep Space Scan, Ensign Pavel Chekov, Excalbian Gamemaster, Lieutenant Nyota Uhura, Pah-Wraith, Seven of Nine, Unassimilated, Species 8472, Suus Mahna Practitioner, The Destruction of Praxis, Warp Speed (15 touched, 13 only).
- **PAR-259 · Planet land tokens and planet-card searches.** "Create a tapped Planet land token named New Planet with '{T}: Add one mana of any color'" (a land token with subtype Planet, a name and a granted mana ability; grep finds no land-token creation yet; verify) and "search for a basic land card or Planet card". Used by the five Anomaly lands (activate, sacrifice, effect, then the token), Genesis Effect/Device, David and Carol Marcus, Saurian Explorer and Stable Wormhole. Cards: Artificial Anomaly, Gaseous Anomaly, Spatial Anomaly, Subspace Anomaly, Temporal Anomaly, David and Carol Marcus, Creators, Genesis Effect, Saurian Explorer, Stable Wormhole, Genesis Device (10; Final Frontier and Warp Speed also need the search form).
- **PAR-260 · Rank-plus-surname self-reference.** Legendary creatures with a rank prefix refer to themselves by rank and surname ("Captain Kirk" for "Captain James T. Kirk", "Dr. Crusher", "Dr. McCoy" for `Dr. Leonard "Bones" McCoy`, "Ensign Kim", "Lieutenant Sulu", "Commander Musiker"); `normalize._fold_self_name` only folds the full name, text before the first comma and the given-name prefix. Fold rank + last word. Measured 2026-11-10: 5 of the 9 flip to `MODELED` from the fold alone (Captain Janeway, Captain Burnham, Commander Raffi Musiker, Dr. Crusher, Lieutenant Sulu); the rest need other clauses. Guard against rank words that are also creature types. Cards: Captain James T. Kirk, Captain Kathryn Janeway, Captain Michael Burnham, Commander Raffi Musiker, Dr. Beverly Crusher, Dr. Leonard "Bones" McCoy, Ensign Harry Kim, Operations, Lieutenant Hikaru Sulu (9).
- **PAR-261 · Quest-counter missions.** "Whenever <event>, put a quest counter on ~. <effect>. If ~ has N or more quest counters on it, <stronger effect>/instead ..." with the threshold deciding the variant or an extra effect (Conquest, Exploratory, Support, Vengeance Mission). Cards: Conquest Mission, Exploratory Mission, Support Mission, Vengeance Mission (4 touched, 4 only).
- **PAR-262 · Flavor-labelled and modal-trigger bodies.** Named mode labels ("Temba, his arms wide —", "Hail —", "Stun —", "Follow the 3rd rule —", "Rewrite the past —", with "choose 1 that hasn't been chosen" and "you lose the game" in Kobayashi Maru Scenario) are not stripped, and two modals fail on mode bodies (Resistance Is Futile: "return target artifact creature card with mana value 3 or less from your graveyard to the battlefield"; Emergency Holographic Crew: "return target Spacecraft card ..."). Cards: Dathon and Picard at El-Adrel, Kobayashi Maru Scenario, Rules of Acquisition, Set Phasers to . . ., Stray from History, Resistance Is Futile, Emergency Holographic Crew (7). Re-check Commander Raffi Musiker, Dr. Leonard McCoy and Captain James T. Kirk (modal ETB/attack triggers, "choose 1 or more instead if you have no cards in hand") after PAR-260.
- **PAR-263 · "If you would draw a card, ..." replacements.** "If you would draw a card, draw two cards instead" (Mr. Spock), "except the first one you draw in each of your draw steps" (Alhammarret's Archive), and "you may instead choose land or nonland and reveal cards until ..." (Pavel Chekov, First Posting). `rules_engine.py` already has draw replacement hooks (Notion Thief, Uba Mask). Cards: Alhammarret's Archive, Mr. Spock, Science Officer, Pavel Chekov, First Posting (3).
- **PAR-264 · Counter placement and entering-counter replacements.** "Other creatures you control enter with an additional +1/+1 counter", "Faeries you control enter with an additional counter for each creature type among non-Borg creatures you already control" (needs MEC-143), "if you would put one or more counters on a creature you control, put twice that many of each kind", "charge counters on an artifact you control: twice / that many plus one", and Dr. McCoy, Surly Surgeon's "instead remove all +1/+1 counters ... damage is healed". Cards: Deanna Troi, Psychic Counsel, Dr. Joseph M'Benga, Lt. Cmdr. Geordi La Forge, Optimization Annex, Dr. McCoy, Surly Surgeon (5).
- **PAR-265 · Copy-with-exceptions, token and enter-as-copy tails (follow-up to PAR-253).** Token copies with added menace/changeling/haste, "except it isn't legendary and it's an Illusion Artifact in addition", "copy of this card ... sacrifice it", X targets each copied, kicker-gated "for each creature target opponent controls" copies, and enter-as-copy of a creature card in a graveyard with extra types and menace/counters (Ezri Dax, Voq, Dominion Saboteur). Cards: Blastoneuron, Dominion Infiltration, Fractured Identity, Mirror Universe Intrusion, Reg Barclay, Fidgety Fantasist, Tasha Yar, Out of Time, Dominion Saboteur, Ezri Dax, Newly Joined, Voq, Torchbearer (9).
- **PAR-266 · Goad variants.** "Goad up to X target creatures", "<creature> and that creature are goaded for as long as you control ~", "all Tribbles get +1/+0 and are goaded" (static goad), and "whenever one or more goaded creatures attack". Goad exists in the engine; verify and extend the "for as long as", X-target and static forms. Cards: Kang, Suspicious Captain, Koloth, Tribble Hunter plus Galvanizing Tenor (MEC-142) (3).
- **PAR-267 · "Tap N untapped <type> you control" as an activation cost.** Tap seven untapped Officers: search for a Spacecraft, put it onto the battlefield with seven charge counters; tap three untapped artifact creatures: draw a card and lose 1 life. Distinct from crew/convoke; reuse the cost parser's tap-creatures machinery if present. Cards: Captain Jean-Luc Picard, Collation Trimatrix (2).
- **PAR-268 · Cast from a non-hand zone with a rider.** "You may cast this card from exile / your graveyard (it enters with a finality counter)", "once during each of your turns you may cast an artifact [creature] spell from your graveyard/the top of your library", plus Zefram Cochrane's "Spacecraft you control enter with two additional charge counters". Reuse `graveyard_cast.py` and `top_library.py` permissions; finality-counter support needs verifying (Excava's catalogue entry documents a simplification). Cards: Khan, Vengeful Heart, Overflow Submatrix, Storied Veteran, Zefram Cochrane, Warp Pioneer (4).
- **PAR-269 · Communicator equipment: "When you cast this spell, copy it" and communicator counts.** Cast trigger that copies the spell itself, and an equipped creature that has a trigger counting "other creatures you control with a communicator attached to them" (unblockable / draw X and put X lands). Cards: Combadge, Starfleet Communicator (2 touched, 2 only).
- **PAR-270 · Disjunctive creature-type lists.** "Klingons and Warriors you control", "Klingon spells and Warrior spells you cast cost {1} less", "attacking Klingons you control get +1/+1", "other Officers, Artificers, Doctors, Pilots, Scientists, and Spacecraft creatures you control get +2/+2", "klingon and warrior creature cards" (a union of subtypes, not an intersection). Cards: Gagh Slinger, I.K.S. Negh'Var, Imperial Flagship, K't'inga-Class Battle Cruiser, Kirk, Man of Action, Kruge, Genesis Seeker, The Promise of Kahless (6).
- **PAR-271 · "Each player reveals the top card of their library, then draws a card" with a consequence from the reveals.** Damage equal to the greatest mana value among the revealed cards; +1/+1 counter for each nonland card. Cards: Alexander, Ship's Fool, Ambassador K'Ehleyr (2).
- **PAR-272 · Hand peek with exile and owner compensation.** "Look at target opponent's hand. You may choose/exile a nonland card from it. That player draws a card / may play it for as long as it remains exiled, costing {2} more". Cards: Salt Vampire, Zero, Incorporeal Sensate (2).
- **PAR-273 · Temporary control grab with untap, haste and riders.** "Gain control of target creature an opponent controls until end of turn. Untap it. It gains haste/trample ... and 'whenever this deals combat damage to a player, create that many tapped Treasure tokens' / becomes a Warrior in addition / at the beginning of the next combat". Cards: Grilka, Widowed Warrior, Worf, Intelligence Contractor, The Wrath of Khan (3).
- **PAR-274 · Reveal until land cards, put onto the battlefield, rest on the bottom in a random order.** Also with a delayed sacrifice of those lands (Will Riker) and a +1/+1 counter on a commander first (Janice Rand). Cards: U.S.S. Voyager, Lone Wanderer, Will Riker, First in the Field, Janice Rand, Essential Aide (3).
- **PAR-275 · Mill then take a card from among them.** "Mill N cards. You may put a permanent/artifact card from among them into your hand" plus a first-spell-this-game rider (First Contact). Cards: First Contact, Transwarp Hub (2; Temporal Anomaly shares the shape).
- **PAR-276 · Put cards from hand onto the battlefield with riders.** "Draw 3 cards. You may put up to three land cards from your hand onto the battlefield tapped", "put a land card from your hand onto the battlefield; if you do, return a land you control at the beginning of the next end step", "put a creature card from your hand onto the battlefield, it gains haste, then put it on the bottom of your library; when you do, draw a card". Cards: Lt. Arex, Ever-Adapting, Erica Ortegas, Plucky Pilot, U.S.S. Farragut, Bold Explorer (3).


## MEC — Game mechanic

- **MEC-139 · Beam me up (RULE 702.196, new).** Two linked static abilities: while the card is in its owner's graveyard it may be cast as an instant or sorcery by paying the beam-me-up cost **and returning a creature you control to its owner's hand** instead of its mana cost (alternative cost, RULE 601.2b/601.2f-h), and when it would leave the stack it is exiled instead (resolves, countered or fizzled alike). Card types still set timing; mana value stays that of the printed mana cost. 702.196b: a creature that "can't be beamed up" cannot pay the return portion (Marooned: "enchanted permanent ... can't be beamed up"). Scotty, Miracle Worker gives every card in your graveyard beam me up during your main phase with the cost equal to its mana cost, and cannot itself be returned for that. Reuse: the Flashback/Escape alt-cost route (`GameEngine._graveyard_cast_keyword`, `graveyard_cast.py`), the `return_pick` cost in `costs.py`, and the exile-on-leaving-stack replacement flashback uses. New: the keyword in `parser/oracle/keywords.py`, the "beamed up" restriction flag, and a legal-actions offer per eligible creature. Add the ISA instruction/effect-type mapping if a new effect type is introduced. Cards: Adversary by Algorithm, Boarding Action, Energize, Federation Resupply, Final Frontier, Open Communications, Pattern Buffer Preservation, Pure Energy, There's Coffee in that Nebula, Transporter Malfunction, Scotty, Miracle Worker, Marooned (12). Secondary blockers: Federation Resupply and Final Frontier (multi-type and planet-card searches, PAR-259), There's Coffee in that Nebula (look-at-5 with "Plains card or nonland permanent card with mana value 3 or less").
- **MEC-140 · Assimilate (RULE 701.72, new).** Keyword action: gain control of a permanent and put a +1/+1 counter on it, or, for a permanent card in another zone, put it onto the battlefield under your control with a +1/+1 counter; either way it becomes a **Borg artifact creature** (loses its other creature types, keeps supertypes, non-creature card types and non-creature subtypes). 701.72c: abilities that assimilate and abilities that refer to permanents "assimilated with [this object]" are linked (RULE 607), so the engine needs a per-source "assimilated" record next to `game/linked_exile.py` (Assimilation Assessor and Borg Cube also say "assimilate a creature card exiled with it", a linked-exile read). The type change must persist as a layer-4 effect for as long as the permanent stays (and a card entering from a graveyard is a new object). ISA instruction `assimilate` (701.72) already exists in `game/isa.py` without an effect type; give it the effect, binder entry and parser verb. Cards: Assimilate the Wounded, Assimilation Assessor, Borg Cube, Borg Queen, Perfection Manifest, Death Is Irrelevant, Gift of Perfection, The Best of Both Worlds, The Borg Queen (8). Tests: from battlefield, graveyard, exile and library; Borg type replaces creature types but keeps "Artifact"; the Best of Both Worlds' chapter III returns "the Borg assimilated with this Saga" to its owner's control; a leaves-and-returns permanent is no longer assimilated.
- **MEC-141 · Face a dilemma (RULE 700.17, new).** A player faces a dilemma whenever they choose one or more modes for a spell or ability; "has faced a dilemma this turn" and "the number of dilemmas faced this turn" (counted per spell/ability, not per mode, so choosing several modes is one dilemma) are read by cards. Needed: one choke point where every mode choice is recorded (modal spells, modal triggers, modal activated abilities; check the Scryfall rulings on whether a copy faces a dilemma), a per-player per-turn counter in `GameState` that survives clone/undo, a `FACED_DILEMMA` event for "whenever you face a dilemma", and the amount/condition readers ("for each dilemma you've faced this turn", "if you faced a dilemma this turn"). A modal trigger with no legal mode (nothing chosen) is not a dilemma. Cards: Captain Benjamin Sisko, Elim Garak, Simple Tailor, Gabriel Lorca, Mirror Menace, Jett Reno, Problem Solver, Melkotian Adjudicator, Obsidian Order Operative, Seven of Nine, Tell Me What You See, The Caretaker (9). Secondary blockers: Captain Sisko (create an Officer token per dilemma; the {2}{W}{U}{B}{R}{G} cast-from-exile ability), Jett Reno (becomes-tapped surveil/draw by power), Tell Me What You See (opponent may have you draw), Gabriel Lorca (return from graveyard for {B}).
- **MEC-142 · Opponents you attacked this turn (Battlefront).** Commander-only ability word counting "the number of opponents you attacked this turn" (creatures that enter attacking do not count; attacking the same opponent in a second combat counts once). The engine already keeps `players_attacked_this_turn` (used by `condition_query.py`, `static_conditions.py`, `effects/damage_draw.py`); verify whether it is per attacker and per opponent for every attack target (player, planeswalker or battle that protects them) and expose it as a dynamic amount (`effect_amounts.py`) and a cost reduction ("costs {1} less for each opponent you attacked this turn"). Parser: the amount phrase and `whenever you attack` bodies that use it. Cards: Galvanizing Tenor, Korok, Liberated Rage, Kurn, Son of Mogh, Martok, Hero of the Empire, Own the Day, Rite of Ascension, The Beacon of Kahless, Worf, Defiant Commander (8). Secondary: Rite of Ascension (tapped and attacking tokens, ENG-55), The Beacon of Kahless (mana equal to the count), Own the Day (additional combat phase, untap attackers).
- **MEC-143 · Federation: creature types among non-Borg creatures.** Ability word counting the distinct creature types among **non-Borg** creatures you control (Changeling counts every type per RULE 702.73 and 205.3m; a Borg creature contributes nothing, even types shared with it, unless a non-Borg creature has them). No `creature types among` amount was found in the engine by grep; add it to `effect_amounts.py`, `continuous.py` counts and the parser (`for every 5 creature types`, `where X is the number of creature types among non-Borg creatures you control`, copies of "instant or sorcery card ... X times", "look at the top X cards"). Cards: Captain Jonathan Archer, Hoshi Sato, Exolinguist, Infinite Diversity, Jean-Luc, Mon Capitaine, Saavik, Stoic Student, Sarek, Federation Ambassador, Starfleet Academy (7). Tests: Changeling, a Borg with shared types, token types, a creature losing types (e.g. Werewolf Pack Leader's updated ability).

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

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock (formerly BUG-45b).** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
