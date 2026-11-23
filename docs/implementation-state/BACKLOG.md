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


Operation families (no single-axis repair; sub-cluster by slot before building):

- **PAR-291 · Player-scoped actions.** `P2 Spielerbezogene Aktionen` 822 / 746 / 320. Remaining cross-dimension pools ("island or blue permanent") and "exiles cards from the top until ..." plus cast riders stay here. PAR-315/317 residue: multi-player scopes (Raging River, Stand or Fall, Butcher Orgg; "you and defending player each": Cait, The River Warlock).
- **PAR-292 · Library inspection and search.** `P2 Bibliothek` 1,049 / 802 / 319. PAR-284 close: Demonlord Belzenlok (repeat-until loop with a put-into-hand-this-way tally). PAR-285 close: Alpine Houndmaster, March of Burgeoning Life, Night Dealings, Ringsight, Savage Order, Wild Pair (search criteria beyond the shared quality / mana-value slots). In progress (M1–M3 done at v1027–1029); residue in `workingOn.md`. PAR-321 close: The Earth King (search shape after its "that many" count).
- **PAR-293 · P/T, keyword grants and characteristics.** `P2 P/T und Keyword-Vergabe` 584 / 562 / 306; `P2 Charakteristik` 146 / 143 / 66. PAR-285 close (mis-scanned as object filters): "becomes a N/N <type> with <quality>" / base P/T: Animate Spell, Ascendant Spirit, Cosmium Confluence, Domesticated Watercourse, Figure of Fable, Fractalize, Gideon Champion of Justice, Opal Guardian, Opal Titan, Optimus Prime Inspiring Leader, Veiled Sentry, Woodcaller Automaton.
- **PAR-294 · Replacement effects.** `P2 Ersatzeffekte` 558 / 550 / 302. PAR-284 close: Unbreathing Horde (prevent damage and remove a +1/+1 counter instead; the entry count parses).
- **PAR-295 · Graveyard returns and zone moves.** `P2 Friedhof` 425 / 415 / 239; `P2 Zonenwechsel` 236 / 221 / 76. "Return target <type> card with mana value N or less from your graveyard" (10 cards, e.g. Can't Stay Away, Orzhov Charm) needs a mana-value key on graveyard target kinds plus one `filter_slots` row. PAR-284 close: Paradoxical Outcome, Revival Experiment (zone-move producers feeding a returned-this-way tally).
- **PAR-296 · Damage.** `P2 Schaden` 400 / 383 / 233.
- **PAR-297 · Tokens and copies.** `P2 Spielsteine` 409 / 379 / 206; `P2 Kopie` 215 / 204 / 53. PAR-285 close: named tokens and token riders: Basri Ket, Bottle-Cap Blast, Brimaz King of Oreskos, Commodore Guff, Dora Milaje Elite, Emrakul and Chatterfang, Forbidden Friendship, Giant Caterpillar, Inquisitorial Rosette, Koma Cosmos Serpent, Koma World-Eater, Nahiri the Unforgiving, Parhelion II, Rukh Egg, Sigiled Sword of Valeron, Tamiyo Compleated Sage, Transluminant, Urza's Hot Dog Stand, Wurmcoil Engine, Wurmcoil Larva ("that's attacking" rider: Brimaz, Inquisitorial Rosette, Sigiled Sword, Parhelion II; two different tokens in one create: Forbidden Friendship, Wurmcoil Engine, Wurmcoil Larva).
- **PAR-298 · Choices.** `P2 Wahl` 998 / 854 / 203: choose, vote, random, naming, piles, bidding. ENG-62 residue: Temporal Firestorm's non-targeted "choose up to X creatures and/or planeswalkers you control ... phase out". PAR-284 residue: vote tallies (Círdan the Shipwright `for each vote they received`, Truth or Consequences `for each consequences vote`, Messenger Jays `feather / quill vote`, Erestor of the Council `opponents who voted for a choice you didn't vote for`) and chosen-card-type reveals (Blood Oath, Fertile Imagination `cards of the chosen type revealed this way`); the amount follows the vote / choice record. PAR-284 close: Intrude on the Mind (pile separation is not a mill), Messenger Jays (vote tally, drawn this way). PAR-285 close: Extinction Event, Mutinous Massacre, Power of Persuasion, Rivals' Duel, Saga of Krark Losing His Thumb, Split the Spoils, Thanos the Mad Titan, V.A.T.S., Wild Swing.
- **PAR-299 · Cast permissions and alternative costs.** `P2 Zauber-Erlaubnis und Alternativkosten` 618 / 595 / 193. PAR-283 residue: Trap alt-cost conditions now take the shared vocabulary; still open are Ravenous Trap ("put into a graveyard from anywhere" tally incl. resolved spells), Cobra Trap (destroyed by an opponent's spell/ability) and Summoning Trap (countered by an opponent) tallies, and Refraction Trap's body. PAR-284 residue: Winged Portent: cleave bracket text `[with flying]` inside a for-each count. PAR-284 close: Dragon Man, Reformed Robot (graveyard cast with an additional discard), Notorious Throng (prowl paid + extra turn); amounts parse. PAR-285 close: Kaervek the Punisher (exile, copy, may cast; lose 2 life if you do), Lara Croft Tomb Raider (discovery-counter play permission), Massimo the Magician (copy through a granted ability); their graveyard picks parse.
- **PAR-300 · Counters.** `P2 Marken` 403 / 374 / 190. PAR-284 close: Cleopatra, Exiled Pharaoh (counter on each of up to two other target legendary creatures). PAR-285 close: Cleopatra Exiled Pharaoh, Katsumasa the Animator, Master's Guidance, Rhino Terrible Trampler.
- **PAR-301 · Cost modifiers and payments.** `P2 Kostenmodifikatoren und Zusatzkosten` 324 / 306 / 172; `P2 Optionale Zahlung` 99 / 98 / 15. PAR-284 residue: scaled payments: `sacrifice ~ unless you pay {1} for each <count>` (Extravagant Spirit, Megatherium, Phantasmal Sphere, Cyclone), `equip - pay 1 life for each card in your hand` (Hand of Vecna); reflexive `when you do` after an optional payment feeding a count (Invisible Woman).
- **PAR-302 · As-enters and enters-with.** `P2 As-enters und Enters-with` 333 / 307 / 144. PAR-314 residue: "As ~ enters, <action>" (119 cards, 32 solo at v937, e.g. Urborg Lhurgoyf's "mill 3 cards for each time it was kicked", Heightened Awareness's "discard your hand") needs an as-enters action form that applies as a replacement (RULE 614.1c), never via the stack; amounts like `source_kicker_count` already bind. PAR-324 close: "if it was kicked, it enters with ..." riders (Dralnu's Pet, Duskwalker, Myriad Construct, Prison Barricade, Ravaging Riftwurm, Voidpouncer).
- **PAR-303 · Exile linkage.** `P2 Exil und Bezug auf exilierte Karten` 382 / 352 / 113. "Exile all [quality] cards from <hand/graveyard>" needs a new zone-exile effect (17 cards, e.g. Identity Crisis, Serum Powder, Hex Magic). PAR-285 close: Ashiok Nightmare Weaver, Bottled Cloister, Duplicity, Epochrasite, Evelyn the Covetous, Haunting Echoes, Ice Cauldron, Identity Crisis, Idol of Endurance, Ignorant Bliss, Leonardo da Vinci, Moonring Mirror, Power Pack, Saprazzan Bailiff, Semblance Anvil, The Animus ("becomes a copy of a card in exile"), Thought Distortion, Tinybones Bauble Burglar, Ultimate Nullification, Wizard's Spellbook, Worldfire, Wormfang Behemoth. PAR-324 close: Waste Management (kicked "exile target player's graveyard" must feed "for each creature card exiled this way").
- **PAR-304 · Attachment and control.** `P2 Anlegen` 190 / 176 / 111; `P2 Kontrolle und Tausch` 102 / 101 / 31. PAR-284 residue: Coveted Falcon: `for each 1 they gained control of this way` tally after the control-exchange clause.
- **PAR-305 · Combat.** `P2 Kampf` 200 / 190 / 100.
- **PAR-306 · Life, draw and discard.** `P2 Leben` 189 / 179 / 78; `P2 Ziehen/Abwerfen` 149 / 146 / 56. PAR-284 residue: discard producers that feed a `this way` tally: `discard your hand` (Balin, Loremaster) and `discard any number of cards` (Rites of Refusal `{3} for each card discarded this way`). PAR-284 close: windowed `drawn this way` pool for a draw producer (Ancient Excavation, Read the Runes; 5 more wait on other clauses).
- **PAR-307 · Mana and energy.** `P2 Mana und Energie` 232 / 210 / 70. PAR-284 residue: `add X mana of any 1 color / any combination of colors / {R} and/or {G}, where X is <count>` host (Klauth, Sanctum of Fruitful Harvest, Xenagos the Reveler, Plasm Capture delayed, Metamorphosis): the amount phrases parse, the `add_mana` any-colour host does not bind a where-X.
- **PAR-308 · Stack interaction and text changes.** `P2 Stapel` 93 / 93 / 65; `P2 Textänderung` 14 / 13 / 10. PAR-284 residue: `counter all spells` producers that feed `for each spell (and ability) countered this way` (Glen Elendra's Answer, Swift Silence). PAR-285 close: Ayesha Tanaka, Frontline Medic, Louisoix's Sacrifice, Mindreaver, Nimble Obstructionist, Ouphe Vandals, The Peregrine Dynamo (counter target ability / spell variants).
- **PAR-309 · Small families.** `P2 Opfern/Zerstören` 170 / 165 / 70; `P2 Zug und Phase` 56 / 56 / 31; `P2 Keyword-Aktionen` 45 / 43 / 18; `P2 Face-down/Transform` 34 / 32 / 14; `P2 Spielausgang und Sonderregeln` 59 / 59 / 13; `P2 Tappen/Enttappen` 51 / 48 / 11; `P2 Phasing` 11 / 11 / 4; `P2 Würfel und Münze` 21 / 17 / 4; `P2 Zähl- und Prozessanweisungen` 22 / 22 / 4; `P2 Bedingte Anweisungen` 28 / 28 / 3; `P2 Tabellen- und Variantenzeilen` 31 / 13 / 3. PAR-284 residue: dice / coin tallies: `roll a d20 for each player being attacked, ignore all but the highest` (Iron Mastiff), `take an extra turn for each coin that comes up heads` (Ral Zarek). PAR-284 close: Out of Time (phased-out-this-way pool; check the phasing event first), Reign of Terror (destroy-all-X-or-all-Y producer, then died this way).

## MEC — Game mechanic

- **MEC-144 · Sideboards as a feature for non-Commander formats.** Sideboard use (cards outside the game, RULE 400.11, 100.4) as a deliberate per-format feature; Commander games stay without one (RULE 903.5f). Scope (per-format rules, matches and sideboarding between games, UI) to be refined before starting. Base: `game/sideboard.py`, `Player.sideboard`.
- **MEC-154 · Saga final-chapter event (RULE 714.2 / 714.3, 603.2).** "Whenever the final chapter ability of a Saga you control triggers / resolves": `SAGA_CHAPTER` fires with the chapter number but carries no final-chapter flag, so no head can tell the final chapter. 3 cards: Historian's Boon, Narci Fable Singer, Tom Bombadil (PAR-286 close).
- **MEC-155 · "Regenerated this way" (RULE 701.19, 614.8).** Regeneration runs through a shield (`damage_death_mixin.regenerate`) with no signal that a given regenerate instruction replaced a destruction. 4 cards: Matopi Golem, Skeleton Scavengers, Debt of Loyalty, Soldevi Sentry (PAR-286 close).
- **MEC-156 · Phase out until the source leaves the battlefield (RULE 702.26, 610.3).** `PhaseOutEffect` knows only the RULE 702.26a untap-step phase-in. Needs a duration linked to the source (as `ExileEffect`'s `until_source_leaves`) so the permanent phases in when the source leaves, the "tap that creature as it phases in this way" rider and a "phased out this way" pool: Oubliette, Out of Time, The Moment (PAR-288 close).
- **MEC-157 · Players play with their hands revealed.** PAR-289 close: no reveal-hand flag exists; needs a static that adds every hand (or one player's hand) to the public knowledge (`GameState.public_card_knowledge`, RULE 400.2 / 701.20) while the source is on the battlefield: Revelation, Wandering Eye, Seer's Vision, Telepathy, Wisedrafter's Will.
- **MEC-158 · Static condition kinds over a permanent's history.** PAR-289 close: `counter_put_this_turn` is kind-blind (Sigardian Paladin, Beast Erudite Aerialist, Kid Loki need the counter kind); "it's modified" (RULE 700.9: Obstinate Gargoyle, Skyward Spider); "it hasn't dealt damage yet" (Karakyk, Palladia-Mors, Ruric Thar); "~ is renowned" (RULE 702.112: Goblin Glory Chaser, Honored Hierarch).
- **MEC-159 · Static condition kinds over game state.** PAR-289 close: "the top card of your library is a <type / colour> card" (Mul Daya Channelers, Vampire Nocturnus, Crown of Convergence); "<colour> is the most common colour among all permanents or is tied" (Goham, Halam, Ruham, Sulam, Zanam Djinn); "your life total is less than or equal to half your starting life total" (Bane, Bhaal, Myrkul).
- **MEC-160 · Per-object counts in group statics.** PAR-289 close (RULE 613.4c): "<group> gets +1/+1 for each other <X> you control / for each of its colours / where X is the number of other <type>" is counted once per affected object, but a group selector counts once against the source, so `rows_typed_groups` refuses it. Needs a count evaluated per affected object: Heroes' Podium, Knight of New Alara, Clamavus, Light from Within, Diligent Zookeeper, Mirror Box, Takeno, Skeletal Swarming.
- **MEC-161 · Non-mana attack and block costs.** PAR-290 close (RULE 508.1g / 509.1c): M2 shipped the mana half (`attack_cost` / `block_cost` combat restrictions, paid with the attack/block tax). Sacrifice / return / tap / life declaration costs and per-attacker sacrifice taxes still need a non-mana declaration cost with a player choice: Exalted Dragon, Floodtide Serpent, Hollow Warrior, Leviathan, Reclamation, Flooded Woodlands, Heat Wave (life per blocker).
- **MEC-162 · Attack and block taxes with an expiry.** PAR-290 close: `attack_tax` / block tax are standing statics; "until your next turn, creatures can't attack you ... unless their controller pays {2} / 2 life" and "this turn, creatures can't attack / block unless their controller pays {X} for each" need a floating form with a clock (RULE 611.2a, 508.1h): Forbidding Spirit, Sivitri, Dragon Master, War Tax, War Cadence, Orzhov Advokist (the last also needs each player's choice).
- **MEC-163 · "Also attacks / also blocks" declaration conditions.** PAR-290 close: "can't attack unless a creature with greater power / at least two other creatures / a black or green creature also attacks" is judged over the whole declaration (RULE 508.1c), not per creature: Okk, Orcish Conscripts, Scarred Puma.
- **MEC-164 · Player cast bars with a next-turn clock.** PAR-290 close: `restrict_target_player_this_turn` ends at end of turn; "can't cast ... until your next turn" / "during that player's next turn" needs a player-scoped floating `cast_prohibition` with that duration (RULE 611.2a): Avatar's Wrath, Conjurer's Ban, Azor, the Lawbringer, Disorienting Glower, Academic Probation, Reflector Mage.
- **MEC-165 · Attack-history conditions.** PAR-290 close: "can't attack if it attacked during your last turn", "creatures that attacked during their controller's last turn can't attack", "unless that player cast a spell or put a nontoken permanent onto the battlefield during their last turn" need per-object and per-player last-turn history: Giant Turtle, Halls of Mist, Arboria.
- **MEC-166 · "Can't crew Vehicles" on a host.** PAR-290 close: an Aura's "enchanted creature can't attack, block or crew Vehicles" needs crew (RULE 702.122) to consult a per-object prohibition; the attack/block/activation halves already exist: Bound in Gold, Intercessor's Arrest, Revoke Privileges.
- **MEC-167 · Fabricate, afterlife, modular, frenzy and poisonous (RULE 702.123, 702.135, 702.43, 702.68, 702.70).** ENG-66 close: the binder docks these keywords as a carried `parametric_keywords` record with no behaviour, even when printed (`binding.core.attach_keyword`; none is in `_KEYWORD_TRIGGERED_BUILDERS`). Build each: fabricate N (ETB, counters-or-Servos choice), afterlife N (dies: N 1/1 Spirit tokens with flying), modular N (enters with counters; dies: move them to target artifact creature), frenzy N (attacks and isn't blocked: +N/+0), poisonous N (combat damage to a player: N poison counters). Then add each to `GRANTABLE_PARAMETRIC_KEYWORDS` so the group grants work: Frenzy Sliver, Virulent Sliver, Enduring Sliver (granted Outlast), Hish of the Snake Cult, Cayth, Famed Mechanist, Arcus Acolyte, Snake Cult Initiation, Indebted Spirit, Afterlife Insurance, Blaster, Combat DJ, Arcbound Overseer. Reuse MEC-152’s printed Outlast activation for the cost-bearing grants on Enduring Sliver and Arcus Acolyte.
- **MEC-168 · Jump-start, encore and typecycling, printed and granted (RULE 702.133, 702.141, 702.29e).** ENG-67 close: ENG-67 built zone-aware keyword grants (`grant_zone_keyword`, `continuous._apply_zone_keyword_grants`, `ZONE_GRANTABLE_KEYWORDS` = unearth; `grant_miracle` with card types and a cost), but jump-start and encore have no engine behaviour even printed (BUG-75) and the cycling binder returns nothing for a typed cycling such as slivercycling. Build each printed behaviour, add it to `ZONE_GRANTABLE_KEYWORDS`, then claim: Graywater's Fixer, Sliver Gravemother, Wire Surgeons (encore), Niv-Mizzet, Supreme (jump-start, plus an "exactly two colors" filter), Homing Sliver (slivercycling, each player's hand). Also verify and grant scavenge (Varolz, the Scar-Striped; Young Deathclaws) and ninjutsu (Satoru Umezawa), whose printed paths exist.
- **MEC-170 · Reveal-a-card additional cost with a chosen card.** MEC-145 close (RULE 601.2b, 701.20): "as an additional cost to cast this spell, reveal a <quality> creature card from your hand" with "the revealed card's mana value" read at resolution. `reveal_from_hand` is only a payability check today: no pick, no public reveal record (`GameState.public_card_knowledge`) and no `revealed` cost referent (the kind exists in `cost_referents`, unrecorded). Cards: Disaster Radius, Induce Despair, Calamity of the Titans.
- **MEC-171 · Reflexive triggers after an optional or plain instruction.** MEC-145 close (RULE 603.12): "you may <discard / exile from your graveyard / tap / amass / sacrifice …>. When you do, <effect reading that object>" outside `pay_cost_then` (the only carrier of `then_trigger`, which auto-picks and records nothing for a plain discard). Needs the instruction's object recorded for the reflexive ability (RULE 608.2h). Cards: Mount Velus Manticore (card types of the discarded card), Argentum Masticore (sacrifice ~ unless you discard; MV bound), Resplendent Marshal (shares a creature type with the exiled card), Nihiloor (per opponent, tapped creature's power bound), Grishnákh, Brash Instigator (amassed Army's power bound), Minsc & Boo, Timeless Heroes (sacrificed creature's power; "if the sacrificed creature was a Hamster").
- **MEC-172 · Target bounds measured from a resolution referent.** MEC-145 close: `targeting.py` bounds "with mana value less than or equal to <count>" by board counts (Drown in the Loch, Lay Down Arms, Betor), not by an amount the resolution produced ("the number of +1/+1 counters removed this way", "the number of colors of mana spent to cast ~", "that amount of excess damage", "that spell's mana value", or MEC-171's referents). Cards: Simic Manipulator, Sundering Archaic, Unleash the Inferno, Saruman of Many Colors; the group-filter sibling Mandate of Abaddon ("destroy all creatures with power less than that creature's power"); then Argentum Masticore, Nihiloor, Grishnákh with MEC-171.

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

- **VIS-22 · Board picker for the opponent-exile cost.** PAR-286 M4: legal actions offer `opponent_exile_cost` (`{count: 1, options: [{instance_id, name, owner_id}]}`) and the session accepts `opponent_exile_choices`, but `gameBoard/castController.js` sends no choice, so a board activation of Cryptic Cruiser / Oracle of Dust / Void Attendant auto-picks the first opponent-owned exiled card. Add the picker next to the `exile_value_cost` / `tap_cost` prompts; verify in a browser.

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


- **BUG-72 · Parsed "target opponent" can target its own controller.** `parser/oracle/catalogue/subgrammars.py` maps `target opponent` to the plain `"player"` target kind (`resolve_target_kind`), so rows that use it, e.g. `effect_rows/damage_copy.py` ("~ deals 3 damage to target opponent"), offer and accept the controller as a target (RULE 115.1 / 102.3: an opponent is another player). Reproduced on Bulwark's upkeep trigger in a 2-player game: the `trigger_target` choice lists p1 and p2 and `resolve_choice("p1")` is accepted. `edicts.py`, `counters_blocking.py` and `destroy_exile_counter.py` already emit `"opponent"`. Fix: map the row to `"opponent"`, size the reshaped MODELED specs with a version-masked full-pool diff, and add a regression test that the controller is not a legal pick.

- **BUG-73 · Mana-ability lines claim any trailing sentence.** Found in PAR-290 M1 review: the segmenter claims a whole `<cost>: Add <mana>. <anything>` line (`parser_probe.py clause "{4}, {t}: add {w}{u}{b}{r}{g}. zorble the frobnicator."` → `segmenter: claimed=True`, the card parses MODELED with no spec for the line), so a rider the mana-ability path does not model is dropped silently. 338 non-authored parser-MODELED cards have a sentence after an `Add` clause; most are known riders ("Spend this mana only ...", "This land deals 1 damage to you", "Activate only ..."), but e.g. Codie, Vociferous Codex, Ether, Brass Infiniscope, Chocobo Camp ("When you next cast ..."), Astrolabe / Barbed Sextant (delayed draw), Avid Reclaimer, Black Tom Cassidy ("If you control ..., you gain N life"), Chandra, Bold Pyromancer and Exploding Barrel need checking against what the mana-ability builder really executes. Make unknown riders fail closed, then re-claim each modelled rider explicitly; report the corrected cards.

- **BUG-75 · Keywords without engine behaviour count as MODELED.** ENG-66 review: 53 non-authored parser-MODELED cards carry a printed keyword the engine only records (modular 21, fabricate 14, outlast 9, afterlife 9; e.g. Arcbound Worker, Arcbound Ravager, Glint-Sleeve Artisan, Angel of Invention, Ainok Bond-Kin, Abzan Falconer, Ministrant of Obligation, Orzhov Enforcer), because `binding.core.attach_keyword` docks any parametric keyword as a record and the gate counts the keyword line as claimed. ENG-67 found the same for printed jump-start (Radical Idea and the rest of the jump-start cards parse MODELED; no cast-from-graveyard route reads it) and for encore. Make the gate refuse a keyword whose behaviour is not wired (a closed list derived from the binder, not from the RULE 702 recognition catalogue), audit every other recognised keyword the same way, and report the cards that drop to UNMODELED; MEC-152 has since implemented printed Outlast. MEC-167 covers printed and granted modular, fabricate and afterlife.

- **BUG-76 · Group sacrifice costs fire their dies events one at a time.** MEC-169 review: `activation_mixin` pays a multi-object sacrifice cost (PAR-232 groups, MEC-169 any-number) victim by victim outside `state.simultaneous()`, so "whenever one or more creatures die" style triggers see separate events (RULE 603.2c / 603.10a; a cost's objects leave simultaneously, RULE 118.3). Last-known information is already correct (records are taken before anyone leaves). Wrap the group in `simultaneous()` as the discard cost does and test with a "one or more" trigger.
- **BUG-77 · Autumn's Veil's targeting restriction never expires.** PAR-324 review: `GameObject.temp_cant_be_target_of_spell_colors` (set by `GrantCantBeTargetOfSpellColorEffect`) is documented as cleared at cleanup (RULE 514.2) but `turn_loop_mixin`'s cleanup pass never clears it, so the "this turn" restriction lasts until the object changes zones. Clear it beside `temp_cant_be_target_of_opponents` and test that a blue/black spell can target the creature next turn.

## REL — Release & deployment

- **REL-1 · Hash-pinned dependency lock.** `requirements.txt` has only `>=` bounds;
  during the release/deployment process, generate a hash-pinned lock that installs on every supported
  platform and the offline wheelhouse (`setup/wheels/`). Open: lock tool (`pip-compile --generate-hashes`
  per platform vs. `uv pip compile --universal`) and whether `setup/install.py` installs from it. Do not
  pin from a dev machine's `pip freeze` (platform-only packages such as `uvloop` would break Windows installs).
