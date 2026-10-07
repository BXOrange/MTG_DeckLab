# Working on — resumable state of the ticket in progress

**The working memory for a ticket that is being built right now.** It exists so that a
new session — after the prompt cache expired, a crash, an update, a context compaction —
continues exactly where the last one stopped instead of re-deriving the state from the
code, the git log and the backlog.

Rules:

- **Read this file first** when you start or resume work on any ticket. If your ticket has
  a block below, continue from its *Next step*; do not re-evaluate what it records as done.
- **One block per ticket in progress**, headed `## <TICKET-ID> · <title>`. Several sessions
  may share this working tree, so never edit another ticket's block.
- **A partly done ticket's residue lives here, not in `BACKLOG.md`.** When a run ends with
  part of the ticket still open, keep its block and record under *Residue* exactly what is
  left (card clusters, blockers, which cards each needs) plus the *Next step*; `BACKLOG.md`
  keeps only the ticket's terse open point (id, title, one-clause scope).
- **Update the block at every milestone**, not only at the end: after a sub-step is built
  and tested, after a decision, before a long-running command (full test tier, coverage
  run), before a commit. Write it so a reader with *no* conversation context can act on it.
- Keep it terse and current — replace stale lines instead of appending. Keep only
  the current resumable state; session logs belong in unversioned temporary files.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (copy below the line, fill in):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PLAY-ALL · Make every saved deck playable

- **Started / last update:** 2026-10-01 / 2026-10-07
- **Goal:** Bring every non-cube saved deck to N/N and fix all recorded correctness gaps (user-confirmed scope); Commander Cube remains optional.
- **Done:** Step 0 (War Room and alternate-name resolution) and Step 1 handler batches completed. General parser results are documented in `Done_Backend.md`. Completed deck coverage: Limit Break 94/94, Counter Blitz 94/94, Multiverse Reforged 93/93, Goblins 39/39, yshtola 97/97, Hydranten 81/81, Raggadragga 84/84, Kodama 75/75, Wick Snail Boom 84/84, Counter Intelligence 94/94, Oops! All Night's Whispers 99/99, World Shaper 87/87, Sultai Arisen 88/88, Mardu Surge 88/88, Calling All Angels 69/69, Jump Scare! 84/84, Abzan Armor 85/85, Living Energy 87/87, Scions & Spellcraft 92/92, Miracle Worker 89/89, Death Toll 88/88, Shorikai Vehicles 89/89, Endless Punishment 86/86, Hope to the last 81/81, Sans Soleil MWI 96/96, Revival Trance 93/93; SpongeBob's last recorded missing card (Gogo) is authored. Turtle Power! is complete at 93/93 with 34 gameplay regressions. Twelve correctness gaps are closed: counter subsets/kinds (Resourceful Defense, Tidus, Rikku), melee (Depthshaker Titan), attacking-you targets (Lulu), forced-defender offers (Territorial Hellkite), creature-owned Mobilize (Infantry Shield), controlled-commander grants (Dancer's Chakrams), reflexive payoffs (Cait Sith, Kujata), one declaration trigger (Within Range), and retained copy abilities (Kimahri). Individual card implementations and their limitations live in `game/card_catalogue/` and `tests/game/catalogue/cards/test_*_deck.py`, not in the Done catalogue.
- **In progress:** Defiler of Vigor/Dreams now prompt for optional life costs; Ward and source-less counters preserve the countering controller; Emet-Selch, Diviner of Mist and Conduit of Worlds cast during resolution with scoped permissions. Regression coverage in `test_play_all_correctness.py` passes in the standard backend tier (12,138 passed, 335 skipped). Full-cache validation passed (12,473 tests); both tiers are green before the user-authorized commit. All remaining correctness gaps and parser/integration follow-ups below remain in scope.
- **Next step:** Commit the validated casting/payment/counter-controller changes, then continue Moraug's combat timing, Yarus's face-down return and Runadi's respondable cast trigger. Turntimber and Esika back-face text is present in the current raw store and card cache: validate their existing back-face paths before adding authoring. Commander Cube remains optional.
- **Decisions:** Prioritize shared parser axes, then decks by marginal cost. Reuse existing primitives before adding new ones. Hand-author isolated gaps; Alchemy is a permanent non-goal. Coverage N/N means MODELED or AUTHORED, not proof that every printed ability is rules-exact.
- **Baselines:** PARSER_VERSION 612 (the equip keyword regex skips "Equip legendary creature"); no other parser changes. Full-cache corpus coverage 20,372/35,046 (58.1%), measured 2026-10-04 at v604 (not re-measured). Latest validation (2026-10-07): standard tier 12,138 passed, 335 skipped; full-cache tier 12,473 passed. Saved decklists are available on this PC; remaining counts below have been remeasured.
- **Known failures:** None in the current backend suites. The phenomenon regression now uses inert departure/destination planes to isolate the encounter trigger from random catalogue effects. Frontend lint remains unverified because Node/npm is unavailable; the changed choice renderer passed V8 syntax/render checks.

### Residue · cards and remaining deck order

- **Coverage (remeasured 2026-10-06 across all saved decks; no unresolved cards):** Every non-cube deck is N/N, including Turtle Power! 93/93. Commander Cube remains optional at 569/749 (180 missing).
- **Batching hint:** the Foundations/Bloomburrow/Tarkir/Aetherdrift/Final Fantasy precons overlap heavily; before each deck, run `--uncovered` and prefer cards shared with other open decks and shared parser axes. Remeasure before ordering further batches.

### Residue · known correctness gaps

Coverage completion does not close these recorded limitations; confirm them against the current card files before fixing them.

- **Raggadragga / Hydranten:** Turntimber's land back face is not authored (only front-face cache text); Yarus returns creatures face up directly, altering ETB/turn-face-up behavior; Runadi's extra entry counters use a standing grant rather than a respondable trigger.
- **Wick Snail Boom:** Chameleon's Mayhem is not supported.
- **SpongeBob:** The Prismatic Bridge back face is not authored (cache limitation); Gogo's copied abilities retain targets.
- **World Shaper:** Moraug untaps when its landfall trigger resolves rather than at the start of the additional combat.
- **Sultai Arisen:** Kotis auto-picks the three other graveyard cards it exiles (oldest first, no prompt); Jarad's Swamp/Forest sacrifice offers a choice for the first half only; Tasigur's "opponent's choice" asks the one opponent you pick with a prompt; Steward of the Harvest borrows mana abilities through the existing borrow machinery, not tested against non-basic activated land abilities beyond Command Tower's.
- **Mardu Surge:** Eliminate the Competition (and Immoral Bargain) sacrifice and choose the X creatures at resolution, not as announced cost and targets; Gix's free casts are zero-cost hard casts (an X in the cost is 0) with no expiry, and the draw-for-life trigger asks the damaging creature's controller; Grenzo's exile permission is the generic "play" window, so an exiled land could also be played; The general printed Mobilize keyword still needs a builder (Infantry Shield now grants a creature-owned attack trigger); Adeline/Ainok never offer the "or a planeswalker they control" defender; Kaya's +1 counter target and Windbrisk's attack count use the existing selectors without a planeswalker-attack special case; Plumb the Forbidden still pays its optional sacrifice at resolution and models copies as scaled draw/life loss; its sacrifice count now uses the actual picks, including tokens.
- **Temur Roar:** Reflections of Littjara's copy keeps the original's targets (no new-target choice, the `CopySpellEffect` simplification); Sarkhan, Soul Aflame's "you may" is the generic do/decline trigger prompt.
- **Calling All Angels:** Emeria Shepherd takes the "Plains: return to the battlefield instead" option whenever it applies (no hand/battlefield choice); Archangel of Tithes' block tax is auto-paid at `declare_blockers` (an unaffordable block is rejected, there is no explicit decline); Serra Avenger's turn count in a Replay board is floored at the round number; Herald of Eternal Dawn's "opponents can't win" is checked in `player_wins` only (a last-player-standing end is not specially suppressed).
- **Jump Scare!:** Experimental Lab // Staff Room — Rooms have no door state, casting the Room is its door unlocking and only the front half exists in the cache; Disorienting Choice chooses its permanents on resolution (not as targets), so hexproof/protection do not stop it; Primordial Mist exiles on resolution rather than as a paid cost (it can be responded to); Kheru Spellsnatcher's standing free cast has no further restriction; Deathmist Raptor asks face up/down only for a card with morph; Yedora's face-down Forest has no turn-face-up route (RULE 708.7).
- **Abzan Armor:** Reunion of the House and Slaughter the Strong choose on resolution (Reunion is "target" in print); Tip the Scales' "when you do" runs immediately instead of as a reflexive trigger; Baldin measures X once for every target; Betor's two targeted halves are two end-step triggers; Colfenor's Urn sacrifices then returns inside one trigger ("if you do" cannot fail there).

- **Living Energy:** Aetherflux Conduit's free casts last the rest of the turn (every nonland hand card is armed, not only while the ability resolves); Territorial Aetherkite's "when you do" damage happens as the payment is made (no separate reflexive trigger); Aetherworks Marvel's `look_top_cast_free` takes the six cards out of the library for the choice (cast from exile, not from the library); Confiscation Coup's control change is permanent via `gain_control_until_eot` ``duration="permanent"`` (no untap/haste); Pia Nalaar's Vehicle token carries its P/T as the printed Vehicle P/T and Crew from its text; Saheeli, Radiant Creator's copy is chosen after the energy is paid (reflexive) but its end-step sacrifice is the delayed trigger shared with Kiki-Jiki.
- **Scions & Spellcraft:** Blue Mage's Cane lets you cast the exiled card itself (not a copy) for {3}, from any opponent's graveyard rather than only the defending player's; Summon: Good King Mog XII targets the token it copies (``token_you_control``) instead of choosing untargeted; Thancred Waters' protection lasts "while it remains on the battlefield" (not "while you control it"); Hildibrand's Adventure permission is a `temp_play_permissions` entry restricted to the back half; Urianger Augurelt exiles the top card face down without a separate look; Estinien counts dealers found in any zone;
- **Miracle Worker:** Rooms are single-door (casting is the unlock; Fear of Sleep Paralysis' "fully unlock a Room" never triggers; Secret Arcade makes only battlefield permanents enchantments, not permanent spells on the stack); Cramped Vents' excess damage ignores damage already marked on the creature; Aminatou's granted Miracle uses the engine's whole-turn miracle window; Aminatou's Augury ends with the turn, so cards not cast stay exiled; Dream Eater's bounce is a reflexive trigger chosen after the surveil; Spirit-Sister's Call and Nightmare Shepherd read the trigger/target object by id (last-known information).

- **Death Toll:** Grist's "isn't on the battlefield, it's an Insect creature" is not a characteristic effect off the battlefield (milling Grist counts as an Insect via `milled_subtype_this_way` ``name: source``, a Grist in your graveyard adds to the −5 via `cards_named_source_in_all_graveyards`); Into the Pit's top-of-library sacrifice is not forced distinct from a spell's own sacrifice cost; Winter selects the graveyard set first and judges it once (a set with fewer than four types does nothing); Old Stickfingers' bottom order uses `random.shuffle`.
- **Shorikai Vehicles:** Dermotaxi's imprint is an enters trigger, not an "as enters" replacement; Kotori's granted Crew 2 stacks with a Vehicle's own Crew N; Rebbec protects by the source's printed mana value (``mv:N`` qualities); The Millennium Calendar's trigger fires on every untap step (untapping nothing adds zero counters).
- **Endless Punishment:** Spiked Corridor // Torture Pit keeps the single-door Room simplification; Vial Smasher the Fierce damages the random opponent only (not an optional planeswalker of theirs); Kardur's goad marks the creatures present as it resolves (later arrivals are not forced); Syr Konrad's graveyard-exit head triggers once per batch of leaving cards, not once per card; Star Athlete/Enchanter's Bane choose their target, then ask its controller; Sadistic Shell Game and `choose_player_objects` ``destroy_not_yours`` resolve all picks together.
- **Hope to the last:** Sphinx of the Revelation pays its X energy as the ability resolves (variable `pay_energy_then`, at least one), not as an announced cost; Riverchurn Monument's "any number of target players" is one target player; Guide of Souls' reflexive "when you do" is a real `then_trigger` but the "becomes an Angel" is a permanent `grant_until` type change; Angel of Destiny's end-step loss counts only players attacked directly (not planeswalkers/battles), and its "that player" life gain needs the DAMAGE event's ``target_id``; Tablet of the Guilds' two colour prompts are mandatory sequential picks (the second excludes the first); Ajani's Pridemate carries its trigger as token oracle text; Teferi's +1 needs explicit ``target_groups`` per slot; Minas Tirith's enters-tapped condition and mana ability come from the oracle text, not the catalogue entry.

- **Sans Soleil MWI:** Portable Hole uses the legacy linked-exile leaves trigger (the return is respondable, and removing the Hole before the enters trigger resolves does not stop exile, unlike RULE 610.3); Dack Fayden, Helping Hand puts creatures onto the battlefield through sequential entry chooser calls rather than one simultaneous entry batch. Both limitations are documented in their card modules.

- **Revival Trance:** Coin of Fate auto-selects the higher-mana-value exiled card for the bottom and returns the cheaper card; Espers to Magicite auto-copies the highest-mana-value creature rather than a reflexive optional target; Sepulchral Primordial chooses at resolution rather than as trigger targets; Rejoin the Fight returns picks as each opponent answers rather than after every pick. Setzer's win payoff is tied to its Vehicle-damage coin flip, so unrelated won flips do not trigger it. Snort asks the controller first and damages each accepting opponent after their own draw. Kefka uses a turn-long free-cast window (including non-instants in the end step), with owner life loss per cast. Strago uses the same-turn window, turn-scoped haste and a one-shot end-step sacrifice. Valigarmanda's chapter I takes the newest matching card per graveyard, and chapters II–IV grant turn-long permissions for all linked spells rather than a single during-resolution cast. Card-specific limitations are documented in the card modules and their effects.

- **Multiverse Reforged:** Tamiyo's batch trigger is one per-creature trigger (same end state); Omnath converts only unrestricted mana; Serra's Emissary does not offer Kindred and protects a player from damage only; Teferi's Reproach's player shield covers damage and life changes, not targeting; Proteus Staff and Jhoira put the rest on the bottom in random order (no owner-chosen order); Venser's spell copies keep the original's targets; The Ur-Sphinx's free-cast window lasts the turn (not only during resolution) and lands are not castable; Jace's attack bar covers every Jace the controller owns, and the opponent's {2} uses the generic pay-or prompt.

- **Counter Blitz:** Auron's, Summon: Ixion's exile returns respondably (linked-exile pair); Collective Effort's Escalate creatures are chosen automatically (lowest power); Rikku's unblockable covers all blockers; Sin removes counters from every artifact, creature and enchantment (the "any number" choice is "all"); Summon: Valefor's tie for greatest mana value is broken in the opponent's favour; Scholar of New Horizons always puts the Plains onto the battlefield when an opponent controls more lands; Summon: Magus Sisters' random mode is a plain random pick.

- **Limit Break:** "Equip legendary creature {3}" (Wrecking Ball Arm) is an authored `attach` ability, not flagged as an equip ability for static cost effects; Barret, Avalanche Leader's attach needs both targets (no "up to one" with a second target); Professor Hojo reads "creature you control" off the ability's target kinds and counts triggered abilities too; Foretell cards read "cast from exile" as `foretold` (Lifestream's Blessing measures X at resolution; Ultimate Magic: Meteor picks the greatest-mana-value artifact or land per opponent); Yuffie's control lasts while Yuffie stays on the battlefield; SOLDIER Military Program "may choose both" is "one or more"; Sephiroth's cell counter makes a creature modified before the 7/5 group is locked only when put on a creature you control first.

### Residue · follow-ups outside individual card coverage

These were recorded as unticketed follow-ups; inspect existing backlog entries before creating duplicates.

- Add parser axes for Defilers' permanent-spell filter, broader mana-ability counter riders (one counter on the source is supported), counter/pump-then-fight, flicker with riders, multi-event attack/block/target heads, equipped-creature X pump, and Turn Inside Out's temporary dies trigger.
- Integration coverage still limited for Patrolling Peacemaker (event fired by hand), Kellan (no real graveyard cast), and Giggling Skitterspike (BLOCKS not exercised in its deck test).
