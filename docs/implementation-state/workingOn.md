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

- **Started / last update:** 2026-10-01 / 2026-10-06
- **Goal:** Bring every non-cube saved deck to N/N in `scripts/deck_coverage.py`; Commander Cube last and optional.
- **Done:** Step 0 (War Room and alternate-name resolution) and Step 1 handler batches completed. General parser results are documented in `Done_Backend.md`. Completed deck coverage: Goblins 39/39, yshtola 97/97, Hydranten 81/81, Raggadragga 84/84, Kodama 75/75, Wick Snail Boom 84/84, Counter Intelligence 94/94, Oops! All Night's Whispers 99/99, World Shaper 87/87, Sultai Arisen 88/88, Mardu Surge 88/88, Calling All Angels 69/69, Jump Scare! 84/84, Abzan Armor 85/85; SpongeBob's last recorded missing card (Gogo) is authored. Individual card implementations and their limitations live in `game/card_catalogue/` and `tests/game/catalogue/cards/test_*_deck.py`, not in the Done catalogue.
- **In progress:** none — Calling All Angels, Jump Scare! and Abzan Armor finished (tests `tests/game/catalogue/cards/test_calling_all_angels_deck.py`, `test_jump_scare_deck.py`, `test_abzan_armor_deck.py`; shared results in `Done_Backend.md`).
- **Next step:** Living Energy (Aetherdrift Commander, 20 missing), then Scions & Spellcraft, Miracle Worker, Death Toll: run `scripts/deck_coverage.py --uncovered "<full deck name>"` (full saved-deck names carry a " - <set> Commander" suffix), hand-author or extend the parser, test, then the full suite (default + `--full-cache` tiers).
- **Decisions:** Prioritize shared parser axes, then decks by marginal cost. Reuse existing primitives before adding new ones. Hand-author isolated gaps; Alchemy is a permanent non-goal. Coverage N/N means MODELED or AUTHORED, not proof that every printed ability is rules-exact.
- **Baselines:** PARSER_VERSION 611 (the lock was re-pinned after a behaviour-neutral whitelist key in `parser/oracle/spec.py`); full-cache coverage 20,372/35,046 (58.1%), measured 2026-10-04 at v604 (not re-measured). Latest pytest after Abzan Armor: 11,989 passed with `--full-cache` (default tier 11,654 passed, 335 skipped). Saved decklists are available on this PC; remaining counts below have been remeasured.
- **Known failures:** None in the latest full backend suite. The phenomenon regression now uses inert departure/destination planes to isolate the encounter trigger from random catalogue effects. Frontend lint remains unverified because Node/npm is unavailable; the changed choice renderer passed V8 syntax/render checks.

### Residue · cards and remaining deck order

- **Deck order by missing cards, ascending (remeasured 2026-10-06 after Abzan Armor with `scripts/deck_coverage.py`; Sultai Arisen, Mardu Surge, Calling All Angels, Jump Scare! and Abzan Armor since closed):** Living Energy 20; Scions & Spellcraft 20; Miracle Worker 20; Death Toll 20; Shorikai Vehicles 21; Endless Punishment 22; Hope to the last 25; Revival Trance 27; Multiverse Reforged 28; Counter Blitz 28; Turtle Power! 28; Limit Break 31; then Commander Cube (202, optional).
- **Batching hint:** the Foundations/Bloomburrow/Tarkir/Aetherdrift/Final Fantasy precons overlap heavily; before each deck, run `--uncovered` and prefer cards shared with other open decks and shared parser axes. Remeasure before ordering further batches.

### Residue · known correctness gaps

Coverage completion does not close these recorded limitations; confirm them against the current card files before fixing them.

- **Counter Intelligence:** Depthshaker Titan does not grant melee; Resourceful Defense moves all counters rather than allowing an arbitrary number.
- **Kodama:** Defiler of Vigor's optional life payment is chosen by the mana solver rather than prompted.
- **yshtola:** Defiler of Dreams uses the same payment simplification; Emet-Selch's graveyard permission lasts the turn rather than being used during trigger resolution; source-less counters (including Ward) do not attribute a countering controller for Baral.
- **Raggadragga / Hydranten:** Turntimber's land back face is not authored (only front-face cache text); Yarus returns creatures face up directly, altering ETB/turn-face-up behavior; Runadi's extra entry counters use a standing grant rather than a respondable trigger.
- **Wick Snail Boom:** Chameleon's Mayhem is not supported.
- **SpongeBob:** The Prismatic Bridge back face is not authored (cache limitation); Gogo's copied abilities retain targets.
- **World Shaper:** Moraug untaps when its landfall trigger resolves rather than at the start of the additional combat.
- **Sultai Arisen:** Kotis auto-picks the three other graveyard cards it exiles (oldest first, no prompt); Jarad's Swamp/Forest sacrifice offers a choice for the first half only; Diviner of Mist and Conduit of Worlds open a rest-of-turn cast window (not resolution-only, as Impulsivity/Rebound); Conduit's "if you haven't cast a spell this turn" is checked when the ability resolves, so a later cast of the chosen card is not re-gated; Tasigur's "opponent's choice" asks the one opponent you pick with a prompt; Steward of the Harvest borrows mana abilities through the existing borrow machinery, not tested against non-basic activated land abilities beyond Command Tower's.
- **Mardu Surge:** Eliminate the Competition (and Immoral Bargain) sacrifice and choose the X creatures at resolution, not as announced cost and targets; Gix's free casts are zero-cost hard casts (an X in the cost is 0) with no expiry, and the draw-for-life trigger asks the damaging creature's controller; Grenzo's exile permission is the generic "play" window, so an exiled land could also be played; Infantry Shield authors Mobilize as the Equipment's own attack trigger (the Mobilize keyword itself has no engine behaviour); Within Range puts one trigger per attacked opponent on the stack instead of one for the table (same totals); Adeline/Ainok never offer the "or a planeswalker they control" defender; Kaya's +1 counter target and Windbrisk's attack count use the existing selectors without a planeswalker-attack special case; Plumb the Forbidden's `sacrifice_count_draw_lose` tail has the same graveyard-snapshot over-count the Immoral Bargain tail had (spell counted as a sacrifice) — verify and fix.
- **Temur Roar:** Reflections of Littjara's copy keeps the original's targets (no new-target choice, the `CopySpellEffect` simplification); Territorial Hellkite's forced defender is enforced when the attack is declared (the engine raises) but not offered by `legal_actions`/bots; Sarkhan, Soul Aflame's "you may" is the generic do/decline trigger prompt.
- **Calling All Angels:** Emeria Shepherd takes the "Plains: return to the battlefield instead" option whenever it applies (no hand/battlefield choice); Archangel of Tithes' block tax is auto-paid at `declare_blockers` (an unaffordable block is rejected, there is no explicit decline); Serra Avenger's turn count in a Replay board is floored at the round number; Herald of Eternal Dawn's "opponents can't win" is checked in `player_wins` only (a last-player-standing end is not specially suppressed).
- **Jump Scare!:** Experimental Lab // Staff Room — Rooms have no door state, casting the Room is its door unlocking and only the front half exists in the cache; Disorienting Choice chooses its permanents on resolution (not as targets), so hexproof/protection do not stop it; Primordial Mist exiles on resolution rather than as a paid cost (it can be responded to); Kheru Spellsnatcher's standing free cast has no further restriction; Deathmist Raptor asks face up/down only for a card with morph; Yedora's face-down Forest has no turn-face-up route (RULE 708.7).
- **Abzan Armor:** Reunion of the House and Slaughter the Strong choose on resolution (Reunion is "target" in print); Tip the Scales' "when you do" runs immediately instead of as a reflexive trigger; Baldin measures X once for every target; Betor's two targeted halves are two end-step triggers; Colfenor's Urn sacrifices then returns inside one trigger ("if you do" cannot fail there).

### Residue · follow-ups outside individual card coverage

These were recorded as unticketed follow-ups; inspect existing backlog entries before creating duplicates.

- Add parser axes for Defilers' permanent-spell filter, broader mana-ability counter riders (one counter on the source is supported), counter/pump-then-fight, flicker with riders, multi-event attack/block/target heads, equipped-creature X pump, and Turn Inside Out's temporary dies trigger.
- Integration coverage still limited for Patrolling Peacemaker (event fired by hand), Kellan (no real graveyard cast), and Giggling Skitterspike (BLOCKS not exercised in its deck test).
