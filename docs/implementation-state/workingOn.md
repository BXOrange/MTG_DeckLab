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
- **Next step:** batch 6 (cycles through `register_family`: Tarkir Will of the Temur/Mardu/Jeskai/Abzan, Siege cycle PAR-99, Heliod's/Erebos's/Thassa's Intervention, Enduring cycle PAR-111, Court cycle), then batch 7, then the Step 2 deck list. Size each with `parser_probe.py blocked` over the whole cache first (batches 1–2 paid off as general axes, not per-deck lists). Then batches 4–7, then the Step 2 deck list.
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
    6. Cycles through `register_family`: Tarkir Will of the Temur / Mardu / Jeskai / Abzan (4 cards, 4 decks), Siege cycle (PAR-99), Heliod's / Erebos's / Thassa's Intervention, Enduring cycle (PAR-111), Court cycle (PAR-139 monarch).
    7. PAR-104 mutagen (7 cards): only with the TMNT deck. PAR-107 to PAR-114 residue batches: only for the deck being worked.
  - **Step 2, decks in marginal-cost order (missing cards):** Goblins 8; Jeskai Striker 16; Family Matters 19; Raggadragga 19 (+1 alias); yshtola 19; Riveteer Rampage 23; Animated Army 19; Hydranten 20; Abzan Armor 23; Wick Snail Boom 23; Counter Intelligence 21; Kodama 22 (+4 aliases); Eternal Might 24; Jump Scare! 25; World Shaper 22; Sultai Arisen 26; Oops! All Night's Whispers 25; Squirreled Away 24; Mardu Surge 22; Death Toll 24; Shorikai Vehicles 26; SpongeBob and the legendary Burger 21 (+3 aliases); Endless Punishment 28; Scions & Spellcraft 27; Peace Offering 24; Living Energy 26; Temur Roar 28; Miracle Worker 25; Revival Trance 31; Counter Blitz 32; Turtle Power! 35 (PAR-104 first); Hope to the last 30; Limit Break 35.
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
