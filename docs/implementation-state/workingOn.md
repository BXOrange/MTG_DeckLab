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

## MEC-128 · Same-graveyard target groups

- **Started / last update:** 2026-10-21 / 2026-10-21
- **Goal of this run:** Fixed-count “exile up to N target cards from a single graveyard”, shared validation/offers and spell/activation/trigger gameplay.
- **Done (built + tested):** Discovery and independent scope reproduction: 11 supported Commander single-blocker candidates; existing unrestricted exile does not model the shared-graveyard relation.
- **In progress:** Not implementing: user redirected this run to a full-pool shared-phrase catalogue before code changes. Owner Codex `/root`, run `20261021-pilot-142418`.
- **Next step:** Implement the shared target relation and literal-count parser sibling; test binding, zero/one/N picks, cross-graveyard rejection, sequential offers, partial target legality and plural-graveyards regression.
- **Decisions:** One-ticket pilot; no commit/push. X and unrelated bespoke riders outside required scope; do not claim them unless binding/gameplay verified.
- **Baselines / artefacts:** Ignored `backend/data/ticket-discover-and-grind-runs/20261021-pilot-142418/`; `manifest.json`, `before.json`, `independent-candidate.json`, `discovery/recommendation.md`. Pool/source and test caches isolated separately.
- **Known failures:** No code changes. Baseline: 14,955 passed, 454 skipped; relative-source-path test failed from repository root and passed on recheck from backend (522 tests). Initial incomplete disposable fixtures were corrected.
- **Residue:** Implementation, independent tests/measurement and delivery pending.
