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
- **Done (built + tested):** v666 exact-visit return batches, interactive host/Aura entry, repeated flickers, Fortune and paper observations remain verified. Conditional returns (Gilraen/Koya/Parting Gust), Identity Thief's battlefield copy snapshot and MEC-124 are in checkpoint `8a06561b`. Vanish into Memory now draws last battlefield power and discards only after successful return, using new toughness after entry choices; Obzedat returns on the original controller's upkeep with persistent, incarnation-scoped haste. Shared multi-card draw offers Dredge per card and retains instruction/replacement remainders through clone/undo. Repeating processes pause for Clash/draw choices and preserve round outcome/cap through clone. Final full-cache: 14318 passed, 1 skipped; focused rider/draw/Miracle/Clash/inventory: 141 passed.
- **In progress:** Remaining source-linked pools, transformed-body compositions, Niko copy duration/linkage and full-family audit. No unfinished runtime edit in the delivered rider/draw milestone.
- **Next step:** Start Safe Haven: reuse `exile(track_exiled_with=True)` and `return_all_exiled_with`, retain exact source/exile visits and migrate returns to interactive batches; test sacrifice success, source blink before resolution, card exile revisits and entry choices. Then Purgatory, Realm Razer, Livio and Niko; audit the full family before closing PAR-157.
- **Decisions:** Reuse existing delayed triggers and entry/dice/payment frames. Another Round reselects each pass. Native/bonus entry counters combine through replacements. Paper observations are fresh facts, never printing metadata. Alchemy remains an explicit non-goal. Checkpoint commit `8a06561b` records the prior verified milestone; the user requested that commit followed by continued PAR-157 implementation.
- **Baselines / artefacts:** v666 coverage `/tmp/par157-riders-coverage.log`: 21617/35046 (61.7%); Commander-legal `/tmp/par157-riders-commander-coverage.log`: 20795/32068 (64.8%). Full-cache `/tmp/par157-riders-final-full-cache.log`. Residual cached-text audit `/tmp/par157-resume-residue-audit.json`; prior-session original 37-card matrix is absent and must be reconstructed from cached text/code/tests.
- **Known failures:** None in the final full-cache or focused gates.
- **Residue:** Full original 37-card family plus classified additions still needs its final audit. Remaining implementations include source-linked pools/interactive returns (e.g. Livio, Safe Haven, Purgatory), transformed-body compositions and Niko's Shard-copy duration/linkage. Verify all adjacent cases against cached Oracle text, finish measurements/status and close only when the full residue is complete.
