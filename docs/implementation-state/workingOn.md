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

## BUG-57 · "Target creature" can't choose the source

- **Started / last update:** 2026-11-09 / 2026-11-09 23:11
- **Goal of this run:** let a plain `target creature` / `any target` choose the ability's own source (RULE 115.1, 603.3d), keeping the exclusion only where the text says "another" / "other", and close the ticket.
- **Done (built + tested):** inventory and sizing only, no code changed (see Decisions).
- **In progress:** delegated to ticket-worker, in parallel with BUG-56's verification (disjoint files, separate commits).
- **Next step:** user/orchestrator decision on the split below, then implement step 1.
- **Decisions:** STOPPED after the inventory: too wide for one ticket and needs one edit in BUG-56's `game/effects/core.py` (`EffectRegistry.create`) or `game/binding/core.py` (`build_effects`). Proposed split: (1) engine: `TargetSpec.exclude_source` flag + `stamped_specs` hook, named other/another frames keep `exclude_source=True`, plain `creature`/`permanent`/`any`/frames stop excluding; (2) parser: `_stamp_distinct_from_others`-style stamp of `exclude_source` for every clause matching `another|other target`, `other than` (PARSER_VERSION 861); (3) sweep of the ~400 MODELED 'another' abilities to prove each still excludes. Original: selected by the orchestrator: small `BUG-*` fixes in ID order; BUG-56 is in final verification.
- **Baselines / artefacts:** PARSER_VERSION 860; `--full-cache` 19968 passed / 4 skipped at `2947c9a9`.
- **Known failures (corrected; final full-cache recheck pending):** none.
- **Residue:** none yet.
- **Inventory (measured, MODELED pool):** abilities whose target kind excludes the source today: plain-text 2048 spell, 1379 activated, 832 triggered, 13 enter_replacement; 'another/other' text 47 spell, 103 activated, 207 triggered, 6 enter_replacement. Kinds: `creature` (1289+905+448 plain), `any` (226 act/197 spell/123 trig), `permanent`, frames defaulting to exclude_source=True (artifact, enchantment, nonland_permanent*, creature_or_planeswalker, ...). Parser maps 'another target creature' and 'target creature' to the same kind (`subgrammars._TARGET_ROWS`, `SOURCE_EXCLUDED_TARGET_KINDS`), so the engine cannot tell them apart without a new flag.
