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

Block template (do not change this, copy below the line, fill in there):

```markdown
## <TICKET-ID> · <title>

- **Started / last update:** <YYYY-MM-DD> / <YYYY-MM-DD HH:MM>
- **Goal of this run:** <which part of the ticket this run closes>
- **Done (built + tested):** <bullets — what is finished, with file/test names>
- **In progress:** <current unfinished implementation>
- **Next step:** <concrete next action>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-185 · Land animation riders

- **Started / last update:** 2026-10-23 / 2026-10-23 15:34
- **Goal of this run:** finish shared land-animation grammar and lifetimes, then continue by dependency rather than coverage.
- **Done (built + tested):** v726 supports retention riders, source/plural pronouns, optional causative forms, multi-land targets, quoted abilities, all creature types, enchanted-land statics/activations and source-bound duration. Self grants lock their battlefield visit; old source-bound grants cannot start after source blink. Runtime tests cover granted activation/expiry, locked groups, attachment and source visits.
- **In progress:** further animation quantities, selectors and per-land durations are being implemented only in isolated `.tmp_par185_next`; original source is the verified v726 milestone.
- **Next step:** commit v726 milestone; reconcile isolated baseline with that commit, inspect/integrate its next delta, then run the complete full-cache suite on the final stable implementation before closing PAR-185. BUG-35 is the verified logical follow-on for Ward prompt cloning; PAR-188/PAR-204 share quantity/optional-antecedent grammar.
- **Decisions:** retention uses RULE 205.1b; resolving groups lock exact visits (611.2c), standing groups remain dynamic. Unsupported inner abilities and unrelated clauses remain fail-closed. Optional targeted counter antecedents belong to PAR-204.
- **Baselines / artefacts:** `%TEMP%/par185_base.json` is v723. `.tmp_par185_v724.json` plus `.tmp_par185_v726_diff.txt` prove v724→v726 +26 / -0. Ledger v726: 22,043/35,046 (62.9%); Commander 21,442/32,068 (66.9%). Status/strategy numbers synced.
- **Known failures / verification:** baseline `tests/services/test_bots.py` times out at its ninth test (also recorded on clean HEAD); excluded from broad run. Full-cache run: 15,822 passed, 1 skipped, 3 failures solely from old exact IR pins; pins updated for intentional `self_subject=True`, both complete affected files independently rerun: 94 passed. Independent final parser contracts: 347 passed; final animation/duration/version tests: 89 passed. No remaining failures in those reruns; final complete run is still required for closure.
- **Residue:** integrate and verify measured X/X, per-object awakening-counter duration, standing/global/target-player groups, legendary/ward and permanent-self variants. Independent blockers: Vitu-Ghazi name setter, searched-batch references, Genju graveyard/inner-ability grammar, certain enters-tapped clauses and Koth's untap subtype target. BUG-35 reproduces with ordinary Ward, independently of animation.
