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
- Keep it terse and current — replace stale lines instead of appending. The log is one
  line per milestone, newest last.
- **On closing the ticket, delete its whole block** (the narrative belongs in
  `Done_Backend.md` / `Done_Frontend.md`); a ticket is closed only once its residue is done
  too. With no ticket in
  progress this file is just this header and the empty template — no ticket id, no log.

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
- **Log:** <YYYY-MM-DD HH:MM — one line per milestone>
```

---

## PLAY-ALL · Make every saved deck playable (order of work)

- **Started / last update:** 2026-10-01 / 2026-10-01
- **Goal of this run:** Plan only. Fix the order of work that takes every non-cube saved deck to N/N in `scripts/deck_coverage.py`.
- **Done (built + tested):** Nothing built. Measured at PARSER_VERSION 564: 56 decks, 20 already N/N, 35 non-cube decks open (725 distinct uncovered cards, about 870 unclaimed clauses), plus the Commander Cube (300 uncovered, ~241 in no other deck, a pool and not a deck).
- **In progress:** Nothing.
- **Next step:** (2026-10-02, this PC lacks most saved decks incl. Jeskai Striker; present: yshtola 14 missing, Hydranten 14, Raggadragga 14, Kodama 16, Wick Snail Boom 16, SpongeBob 19 — take them in that order, one deck per loop.) Step 2, next deck: Jeskai Striker (re-measure first with `deck_coverage.py --uncovered`; Goblins is done), hand-author what the new axes did not close. Size each with `parser_probe.py blocked` over the whole cache first (batches 1–2 paid off as general axes, not per-deck lists). Then batches 4–7, then the Step 2 deck list.
- **Decisions:**
  - Decks barely overlap (Tarkir 115 uncovered = 115 distinct, Duskmourn 102 = 102). Finishing one deck does not help the next, so order by marginal cost, not by set. Set-by-set is only a familiarity choice.
  - 599 of the 725 cards have exactly one unclaimed clause and no two share an exact template. Hand-authoring dominates, and only ~83 cards sit on an open BACKLOG cluster. Handlers shrink the bill but do not remove it.
  - Per-deck size is flat (16 to 35 missing). The real levers are the free wins in Step 0 and the handler batches in Step 1.
  - Cube is last and optional. Step 1 handlers (PAR-102 especially) shrink it for free.
- **Baselines / artefacts:** `scripts/deck_coverage.py --uncovered` (2.7s). Per-card unclaimed clauses come from `parse_oracle(card).unclaimed` as in `commander_tail_report.py`. Singleton rows were last checked at PARSER_VERSION 552, so re-run `parser_probe.py blocked` before hand-authoring each card.
- **Known failures:** None known.
- **Residue:**
  - **Step 0, DONE 2026-10-01:** War Room hand-authored (`PAY_LIFE_COMMANDER_COLORS`); 14 Universes Beyond alt names in 6 saved decks renamed to the real Oracle names (backup of decks.db in the session scratchpad only). Vivi B4, Ojer cEDH, cEDH staples 2, Silverquill Influence now N/N; Raggadragga/SpongeBob/Kodama each lost their unresolved lines.
  - **Step 1, handler batches before the big decks.** Counts are saved-deck cards touching the clause, an upper bound (a card with several unclaimed clauses needs all of them). Measure the real unlock with `parser_probe.py` first.
    1. **DONE 2026-10-01 (PAR-144, v565, +115):** the dig grammar (`catalogue/dig.py`). Of the 12 saved-deck cards, 7 are now MODELED (Grisly Salvage, Growing Rites, Monumental Henge, Muxus, Paradox Surveyor, Ureni, Weatherlight). Left for hand-authoring at their decks: Genesis Hydra, Genesis Wave, Geometer's Arthropod (all `x`, refused on purpose), Atraxa, Grand Unifier (per-card-type pick), Wrenn and Seven (its `0:` ability is a separate gap). Open dig axes are listed in the Done_Backend PAR-144 entry.
    2. **DONE 2026-10-01 (v566, +99):** PAR-136 (flicker + delayed return), PAR-137 (impulse-draw variants), PAR-138 ("counters are put on" head) closed and deleted from BACKLOG; PAR-139 then closed completely in a follow-up run (madness-`{X}` overrides, corpse-counter reanimation with `exile_instead_of_leaving`, Phyrexian Vindicator's reflexive rider, one-shot shields with riders, counter-gated shields) — deleted from BACKLOG; narratives are in the Done_Backend entries. Three general parser fixes rode along (sentence windows, mid-body "where x is", list commas in a trigger condition). Leftover clusters per ticket are in the Done_Backend entry.
    3. **PAR-109 DONE 2026-10-01 (v567, +131 with PAR-139; terse residue in BACKLOG). PAR-102 DONE 2026-10-01 (v568, quoted grant / keyword choice / "that creature dies this turn" / while-tapped / toxic / all types; closed and deleted from BACKLOG, leftovers in the Done_Backend entry).**
    4. **DONE 2026-10-01 (v569, +31): token copy** — see the Done_Backend "Batch 4" entry (leftovers listed there; not ticketed).
    5. **DONE 2026-10-01 (v570, +84): PAR-105 + counters on each [other] `<group>` + graveyard cast permissions** — see the Done_Backend "PAR-105 + batch 5" entry (PAR-105 deleted from BACKLOG; leftovers listed there).
    6. **DONE 2026-10-01 (v571, +111, 1 dropped on purpose): the cycles, as shared axes** — see the Done_Backend "Batch 6" entry (all saved-deck cards on the list are MODELED and execute; PAR-99 closed 2026-10-01 (v572, +5: the targeted-spell tax, see Done_Backend), PAR-111 lost the Enduring bullet; leftovers listed there).
    7. PAR-104 DONE 2026-10-01 (v576, +34; see Done_Backend). PAR-107 to PAR-114 residue batches DONE 2026-10-02 (v577–v583, closed; leftovers per card in the Done_Backend run-3 entry).
  - **Step 2, decks in marginal-cost order (missing cards):** ~~Goblins~~ done; Jeskai Striker 16; Family Matters 19; Raggadragga 19 (+1 alias); yshtola 19; Riveteer Rampage 23; Animated Army 19; Hydranten 20; Abzan Armor 23; Wick Snail Boom 23; Counter Intelligence 21; Kodama 22 (+4 aliases); Eternal Might 24; Jump Scare! 25; World Shaper 22; Sultai Arisen 26; Oops! All Night's Whispers 25; Squirreled Away 24; Mardu Surge 22; Death Toll 24; Shorikai Vehicles 26; SpongeBob and the legendary Burger 21 (+3 aliases); Endless Punishment 28; Scions & Spellcraft 27; Peace Offering 24; Living Energy 26; Temur Roar 28; Miracle Worker 25; Revival Trance 31; Counter Blitz 32; Turtle Power! 35 (PAR-104 first); Hope to the last 30; Limit Break 35.
    - Cards in several decks: hand-author them at the first deck that has one (Mosswort Bridge in 4 decks; Tear Asunder, Time Wipe, Combustible Gearhulk, Victimize, Multani, Disciple of Bolas in 3 each; War Room is already done).
  - **Step 3, Commander Cube (last, optional):** ~241 cube-only cards, ~275 clauses of hand-authoring.
  - **Effort estimate:** ~725 cards; if Step 1 closes 100 to 150, ~600 remain by hand. At about one deck per session earlier (Marchesa, Vivi), expect ~30 to 35 sessions for Steps 2 and 3, 1 to 2 for Step 0, 4 to 6 for Step 1.
- **Log:**
  - 2026-10-01 — Coverage measured, cards classified, order proposed, block filed.
  - 2026-10-01 — Step 0 done: War Room + alias renames; full pytest 9998 passed (before the deck renames, which touch no tests).
  - 2026-10-01 — Step 1 batch 1 done: PAR-144 dig family (v565, 19,176 / 35,095, +115, 0 regressed); full pytest incl. `--full-cache` 10348 passed; CLAUDE.md/PARSER_LONG_TAIL/status.{de,en}.js/Done_Backend/BACKLOG ids synced.
  - 2026-10-01 — Step 1 batch 2 done: PAR-136/137/138 closed, PAR-139 mostly (v566, 19,275 / 35,095, +99, 0 regressed); full pytest incl. `--full-cache` green after two stale test pins were updated (Professor Onyx's +1 is now dig-claimed; the condition-vocabulary pins gained `madness_cost_paid`).
  - 2026-10-01 — Step 1 batch 3 part 1: PAR-139 closed, PAR-109 closed to a terse residue (v567, 19,406 / 35,095, 0 regressed); full pytest incl. `--full-cache` 10445 passed; docs/number sync + memory done. Stormforged Armor/Kari Zev need Alchemy `conjure` (~170-card family) — not filed, user to be told.
  - 2026-10-01 — Alchemy declared a permanent non-goal by the user (DEFERRED.md already lists it; memory saved). PAR-102 part 1 built: quoted grant / all types / while-tapped / toxic / keyword choice (+38 in the probe).
  - 2026-10-01 — Step 1 batch 3 part 2: PAR-102 closed (v568, 19,452 / 35,095, Commander 18,699 / 32,116, 0 regressed); full pytest incl. `--full-cache` 10474 passed; docs/number sync + memory done.
  - 2026-10-01 — Step 1 batch 4: token copy (v569, 19,483 / 35,095, Commander 18,728 / 32,116, +31, 0 regressed); full pytest incl. `--full-cache` 10508 passed; docs/number sync done.
  - 2026-10-01 — Step 1 batch 5: PAR-105 + graveyard cast permissions + group counters (v570, 19,567 / 35,095, Commander 18,808 / 32,116, +84, 0 regressed); full pytest incl. `--full-cache` green after one stale pin ("each nonblack creature") was updated; docs/number sync done.
  - 2026-10-01 — Step 1 batch 6: Siege/Enduring/twice-X/wheel/greatest-stat/damage-equal-count (v571, 19,677 / 35,095, Commander 18,917 / 32,116, +111, Secluded Starforge dropped on purpose); full pytest incl. `--full-cache` green (one random planar-deck flake in `test_casual_variants`, passes alone); docs/number sync done.
  - 2026-10-01 — PAR-99 (the targeted-spell tax, closed and deleted from BACKLOG): v572, 19,682 / 35,095, Commander 18,922 / 32,116, +5, 0 regressed; full pytest incl. `--full-cache` 10589 passed; docs/number sync done.
  - 2026-10-01 — PAR-111 (closed and deleted from BACKLOG; BUG-2 filed): v573, 19,709 / 35,095, Commander 18,947 / 32,116, +27, 0 regressed; Exploit is now a real mechanic; docs/number sync done.
  - 2026-10-01 — PAR-104 (closed and deleted from BACKLOG): v576, 19,743 / 35,095, Commander 18,979 / 32,116, +34, 0 regressed; full pytest incl. `--full-cache` green after one stale pin was replaced; docs/number sync done.
  - 2026-10-02 — PAR-107…114 closed (v584, 20,107 / 35,095, Commander 19,340 / 32,116, +84 over v581, 0 regressed); full pytest incl. `--full-cache` 10,811 passed; docs/number sync done.
  - 2026-10-02 — Step 2, Goblins deck done (39/39): 6 hand-authored (Goblin Matron, Goblin Rabblemaster, Krenko Tin Street Kingpin, Legion Loyalist, Wort Boggart Auntie, Coat of Arms; `tests/game/catalogue/cards/test_goblins_deck.py`) + Surge built as an engine mechanic (RULE 702.117, v585, 20,116 / 35,095, Commander 19,349 / 32,116, +9, 0 regressed; `tests/test_surge.py`); plain pytest and `--full-cache` green (10,829 passed); docs/number sync + Done_Backend entries done. Goblins removed from the Step 2 list.
  - 2026-10-02 — Step 2, yshtola (this PC; 14 missing) in progress: Stormscape Familiar hand-authored (`tests/game/catalogue/cards/test_yshtola_deck.py`). Open: Baral (needs a "spell/ability you control counters a spell" trigger), Battlefield Thaumaturge (cost reduction per creature targeted), Bloodchief Ascension, Case of the Ransacked Lab, Cloud Key (needs a choose-card-type-on-enter replacement), Defiler of Dreams, Dragon's Prey (self tax if it targets a Dragon; the offer-time probe would overstate it), Emet-Selch, Faebloom Trick, Fandaniel, Generous Gift, Leadership Vacuum, Sygg.
  - 2026-10-02 — yshtola: Generous Gift hand-authored (Beast Within's shape, Elephant token; test in `test_yshtola_deck.py`). 12 left; Faebloom Trick/Leadership Vacuum need a reflexive-trigger / command-zone-return primitive each (not found in `game/effects`).
  - 2026-10-02 — yshtola: Faebloom Trick hand-authored (`create_token` + `reflexive_trigger` + `tap`; test answers the `trigger_target` choice). Correction to the entry above: the reflexive primitive DOES exist (`reflexive_trigger`, Meanders Guide). 11 left; Leadership Vacuum (command-zone return) is the only one still without a primitive found.
  - 2026-10-02 — yshtola: Bloodchief Ascension hand-authored (STEP_BEGIN end + `opponent_lost_life_this_turn` active_if; PUT_INTO_GRAVEYARD + `source_counters` quest>=3; both optional). Tests drive a real `lose_life` / `destroy` + `announce_graveyard_arrivals`. 10 left: Baral, Battlefield Thaumaturge, Case of the Ransacked Lab, Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch, Fandaniel, Leadership Vacuum, Sygg.
  - 2026-10-02 — yshtola: Battlefield Thaumaturge hand-authored; new `per_target` flag on `cost_reduction` (`continuous.cost_reduction_for`, scales the `reduce_if_targets` discount by matching targets; probe counts 1). 9 left: Baral, Case of the Ransacked Lab, Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch, Fandaniel, Leadership Vacuum, Sygg. **Found, not fixed (out of scope):** `reduce_if_targets` criteria go through `combat.matches_object_filter`, which ignores an unknown key — Killian, Ink Duelist's `{"is_creature": True}` therefore matches *any* object target (a land too); it should be `{"card_type": "creature"}`. Needs its own ticket/one-line fix.
  - 2026-10-02 — yshtola: Sygg, River Cutthroat hand-authored (Bloodchief's end-step shape, `draw`, min 3). 8 left: Baral, Case of the Ransacked Lab (needs the Case solve condition "cast 4+ instants/sorceries this turn"; the rest parses), Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch (graveyard-cast discount + once-per-turn cast trigger), Fandaniel (opponent sacrifice-or-lose-life), Leadership Vacuum.
  - 2026-10-02 — yshtola: Case of the Ransacked Lab hand-authored; new `count_selector` key `instant_and_sorcery_spells_cast_this_turn` (continuous.py) feeds the "To solve" `control_count` condition. A parser follow-up would add the `_TO_SOLVE_CONDITION_RES` row for "you've cast N or more instant and sorcery spells this turn" — not done (out of scope, unticketed). 7 left: Baral, Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch, Fandaniel, Leadership Vacuum.
  - 2026-10-02 — yshtola: Fandaniel, Telophoroi Ascian hand-authored (`for_each` each_opponent + `pay_cost_then` payer=target, else `lose_life` with a `count_selector` amount x2; no new primitive; both branches tested). 6 left: Baral, Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch, Leadership Vacuum.
  - 2026-10-02 — yshtola: Leadership Vacuum hand-authored; new effect `return_commanders_to_command_zone` (`library.ReturnCommandersToCommandZoneEffect`, registry.py, classified `move_object` in isa.py; targets a player, fires LEAVES_BATTLEFIELD, resets the object, sends each commander the target controls to its owner's command zone). Test covers an opponent's commander with counters, a non-commander, and my own commander (untouched), plus the draw. 5 left: Baral (no "counters a spell" event exists), Cloud Key (choose-card-type-on-enter), Defiler of Dreams (optional life cost + blue-only discount), Dragon's Prey (self tax if it targets a Dragon), Emet-Selch (graveyard-cast discount + once-per-turn cast permission).
  - 2026-10-02 — **yshtola parked at 9 hand-authored** (Stormscape Familiar, Generous Gift, Faebloom Trick, Bloodchief Ascension, Battlefield Thaumaturge, Sygg, Case of the Ransacked Lab, Fandaniel, Leadership Vacuum); residue = Baral, Cloud Key, Defiler of Dreams, Dragon's Prey, Emet-Selch (each needs its own engine piece, listed above). Next deck: Hydranten (14 missing).
  - 2026-10-02 — Hydranten: Primal Vigor hand-authored (`test_hydranten_deck.py`); `double_tokens` gained `any_controller`, `double_counters` gained `recipient="creature"` (`effects/replacements.py`). 13 left: Genesis Hydra, Geometer's Arthropod, Herald of Secret Streams, Icy Blast, Kodama of the West Tree, Kurbis, Mana Reflection, Mathemagics, Mind into Matter, Neverwinter Hydra, Power Sink, Runadi, Simic Ascendancy.
  - 2026-10-02 — Hydranten: Herald of Secret Streams hand-authored (`grant_keyword` `cant_be_blocked` over `has_counter_kind: +1/+1`; test asks the real `engine.can_block`, not the module-level `combat.can_block`, which does not read this flag). 12 left: Genesis Hydra, Geometer's Arthropod, Icy Blast, Kodama of the West Tree, Kurbis, Mana Reflection, Mathemagics, Mind into Matter, Neverwinter Hydra, Power Sink, Runadi, Simic Ascendancy.
