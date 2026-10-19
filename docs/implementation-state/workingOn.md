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

## PAR-157 · Flicker with riders

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** Resolve the independent audit's explicit-source return-rider defect; verify the previously closed mechanism.
- **Done (built + tested):** Native activation/death-trigger regressions reproduce named-source keyword/counter failure. Shared return batches now carry original source capture and exact operation-owned source return visit; return continuations rebind only that successful visit and restore the outer capture. Source-return tails use the same continuation; measured X traverses its nested return body. Twenty-four regressions cover failed/stale returns, separate sources, group returns, entry-choice clones and ordinary hand/library entry batches.
- **In progress:** Final full-cache suite on parser 688; focused PAR-157 gate passed 527 tests before two additional ordinary-entry regressions.
- **Next step:** Wait for final full-cache result, then hand over for independent review and reclosure.
- **Decisions:** Rebind only the exact successfully returned source for that continuation. Never globally refresh an old source capture or substitute an unrelated returned target. Missing ordinary back-face actions remain outside PAR-157.
- **Baselines / artefacts:** Commit e793dbe5; parser 687 snapshot /tmp/par157-source-base687.json. Parser 688 final probe +0/-0; fresh authoritative overall 21780/35046 (62.1%), Commander 20952/32068 (65.3%). Full-cache log /tmp/par157-source-full688-final.log; isolated cache /tmp/par157-cache and data /tmp/par157-grinder-data.
- **Known failures:** None in focused gate; original named-source and measured-return regressions pass. Full-cache result pending.
- **Residue:** Shared fix, regression matrix, full-cache gate, scope review and reclosure. Cross-game behavior is permanently Unsupported per user decision; PAR-168 follows after acceptance.

## PAR-168 · Permanent non-goal support classification

- **Started / last update:** 2026-10-19 / 2026-10-19
- **Goal of this run:** Apply the user's Unsupported decision consistently to cross-game interactions and permanent Deferred mechanics, including Alchemy-only cards.
- **Done (built + tested):** Raw metadata audit distinguishes digital printings of paper cards from digital-only cards; permanent versus parked Deferred scope verified. MEC-125, MEC-48 and MEC-98 are permanent non-goals, not implementation backlog.
- **In progress:** Disjoint metadata/pure-policy stage only; no parser/runtime hookup until PAR-157 acceptance.
- **Next step:** Worker: preserve support metadata through Card/conversion/cache and test a shared pure policy. Then connect policy ahead of authored overrides, expose Unsupported in APIs/UI and remeasure coverage with intentional policy changes separated from regressions.
- **Decisions:** A digital printing alone is not Alchemy-only; preserve ordinary paper cards and supported Vanguard base modifiers. PLR-14 is merely parked. No cross-game subsystem will be implemented.
- **Baselines / artefacts:** Worktree /tmp/mtg-par157-mec-audit; isolated cache /tmp/par157-cache, deck fixtures /tmp/par157-grinder-data.
- **Known failures:** Permanent non-goals other than stickers currently lack a uniform Unsupported verdict/badge; authored coverage can override parser exclusions.
- **Residue:** Metadata/policy, parser/registry/API/UI integration, full/targeted tests, measured coverage, documentation and independent verification.
