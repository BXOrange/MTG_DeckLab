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
- **In progress:** <what is half-built right now, and in which files>
- **Next step:** <the exact next action — command to run or change to make>
- **Decisions:** <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures:** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## PAR-157 · Flicker with riders

- **Started / last update:** 2026-10-16 / 2026-10-17
- **Goal of this run:** Complete the bounded flicker/rider family, including composed and paper Un-set cases.
- **Done (built + tested):** v665 exact-visit returns, shared serializable entry batches, repeated rounds, Acrobatics, Fortune and physical observations remain in place. Flickerform/Coffin now use interactive host/Aura batches; host copy choices survive clone and Aura entry cannot follow a new host visit. Fixed optional blink target-count maxima; Teferi's Time Twist uses post-copy creature entry counters. Gilraen, Koya and Parting Gust are authored over shared exact-visit return/payment choices (9 execution tests). Identity Thief captures last battlefield copiable values, including transformed faces and copied creatures (3 execution tests). MEC-124's state-owned additional end steps, first-end-step tracking, clone/resume and real Y'shtola trigger loop pass 5 execution tests. Focused gate before Identity Thief: 585 passed; latest return-family gate: 64 passed.
- **In progress:** Remaining PAR-157 card semantics and full-family audit; delivered v666 milestone and MEC-124 dependency are verified.
- **Next step:** Implement Vanish into Memory’s pre-exile power draw and successful-return/current-toughness discard using exact-visit batches and existing draw/discard continuations; then Obzedat, source-linked pools and Niko’s copy duration. Audit the complete family before closing PAR-157.
- **Decisions:** Reuse existing delayed triggers and entry/dice/payment frames. Another Round reselects each pass. Native/bonus entry counters combine through replacements. Paper observations are fresh facts, never printing metadata. Alchemy remains an explicit non-goal. Do not commit without a user request.
- **Baselines / artefacts:** Resumed v665 `/tmp/par157-resume-base.json` (21610 covered names); v666 authoritative coverage `/tmp/par157-resume-coverage.log` (21615/35046, 61.7%). Residual cached-text audit: `/tmp/par157-resume-residue-audit.json`. Prior-session `/tmp/par157-*` scope/matrix artefacts are absent; reconstruct scope from cached Oracle text and existing tests.
- **Known failures:** None in final v666 full-cache gate: 14304 passed, 1 skipped (`/tmp/par157-final-full-cache.log`). Focused inventory/lock/conditional/copy/end-step gate: 94 passed. Final probe versus resumed v665: +5 covered / -0 regressed (`/tmp/par157-resume-final-diff.log`).
- **Residue:** Full original 37-card family plus classified additions still needs its final audit. Remaining implementations include successful-return riders (Vanish into Memory, Obzedat), source-linked pools/interactive returns (e.g. Livio, Safe Haven, Purgatory), transformed-body compositions and Niko's Shard-copy duration/linkage. Verify all adjacent cases against cached Oracle text, finish measurements/status and close only when the full residue is complete.
