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
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
- **On closing the ticket, delete its whole block.** Durable results for shared
  engine/parser features belong in `Done_Backend.md` / `Done_Frontend.md`;
  individually modeled cards stay documented in their implementations and tests,
  not in `Done_Backend.md`. A ticket is closed only once its residue is done too.
  With no ticket in progress this file is just this header and the empty template
  — no ticket id, no log.

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested, 23 new tests in test_par249_token_names_creating_card.py):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

---

## PAR-281 · Offer filter slots on every row

- **Started / last update:** 2026-11-16 / 2026-11-16
- **Goal of this run:** whole ticket: one ordered, fail-closed peeler step around `handlers.match_clause` that strips `with <quality>` / `from <zone>` filter slots rows already read, so the ~99 known-good-filler sentences claim (RULE 601.2c respected).
- **Done:** `catalogue/filter_slots.py` (`peel_filter_slots`, hooked last in `handlers.match_clause`): library-search carrier (exact/alternative mana value, power-or-toughness bound, catalogued keywords) into `criteria`; PARSER_VERSION 914 + history + lock; `tests/test_par281_filter_slots.py` (13 pass). Full-pool spec diff v913 -> v914: 10 gained, 0 lost, 0 changed.
- **In progress:** nothing. Milestone 1 (search carrier) committed; suite 23,203 passed / 505 skipped; `find_fragments.py --all-cards --axes` v914: 8,858 open, assignment complete.
- **Next step:** milestone 2: add `_CARRIERS` entries (each with an engine reader, or the reader built first) for the largest residue clusters: "exile all cards from <hand/graveyard>" with a quality (12), graveyard exile/return with counter/legendary/historic riders (~14), `counter_ability`/`copy_target_ability` "from <kind> source" (11), enters-with custom counters (8). Then edicts, Stern Scolding, `choose_targets` mana value. Dynamic search qualities and the ~66 condition/amount sentences go to PAR-283/284 at close.
- **Decisions:** pytest `--full-cache` tier not run per ticket (user instruction); full-pool spec diff with zero lost cards is still the acceptance check.
- **Baselines / artefacts:** scratchpad par281/: basespecs.json (v913 per-card spec hashes), specdump.py, diff1.json(.gainedspecs).
- **Known failures:** -
- **Residue:** the 99 "slot" sentences are not one gap: a quality is only claimable where an engine reader exists for it. Carried now: library search (10 cards). No reader yet (each is its own engine/param ticket, peel must stay refused): edict sacrifice filters (Clip Wings, Run Afoul, Exile into Darkness, Pick Your Poison), `counter_ability`/`copy_target_ability` "from <kind> source" (11), "exile all cards from <hand/graveyard>" (12), "exile/return ... cards from graveyard" with counters/legendary/historic (about 14), `counter` spell power/toughness filter (Stern Scolding), enter-with custom counters (mannequin/finality/hexproof; 8), `choose_targets` mana-value filters (3), dynamic search qualities ("same name as", "mana value equal to ...": 9). ~66 condition/amount-axis sentences were not touched: their slot gap is per-row, not a shared peel.
