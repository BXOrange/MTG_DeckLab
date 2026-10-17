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
- **Goal of this run:** Generalize the remaining flicker work as shared subject/capture, exile-phase, copy-recipient, timing, entry and successful-return axes; migrate bespoke adapters instead of adding card-specific runtime types.
- **Done (built + tested):** v666 checkpoints `8a06561b`/`e32f8cb4` and the linked-pool/timed-copy milestones remain verified. `effects/exile_sequences.py` now owns shared blink phases: subject selection, departing copy snapshot/filtered recipients, intervening effects, return timing/entry and successful-return bodies. Four dedicated rider/copy runtime types are removed; seven existing catalogue cases compose blink/bind/grant instead. Transformed-return compatibility delegates to the same pipeline. Pool payment/counter names live in catalogue data. Parser v667 composes source/target, timing, transformed entry, shared open counter-kind grammar and safe untargeted riders. Unregistered combinations execute through entry/draw choices and clone/undo. Shared Saga completion now protects pending final chapters; single-faced cards cannot enter transformed. Full-cache: 14374 passed, 1 skipped; focused modularization/families/lock gate: 294 passed. Probe: +4 covered, 0 regressed.
- **In progress:** No unfinished runtime edit in the modularization milestone. Remaining work is organized by shared capabilities below, not by new card-specific effect classes.
- **Next step:** Centralize remaining linked-pool producers/transfers around `GameState.linked_exile_visits`: migrate cost/search/choice writers and `TransferExiledWithToCreatedEffect` using the already captured cost IDs/incarnations, then retire ID-only return fallback once every producer is migrated. Continue with exact event-derived groups, frozen pre-exile controller branches, exile-zone grants/return choices and reachable back-face support. Extend shared mechanisms and use catalogue entries only for composition.
- **Decisions:** User explicitly requested generalization/modularity. Selection, measurements, timing, entry and follow-up instructions are separate axes; reuse bind/seq/choices/blink before adding any runtime type. Existing transformed-return spelling remains a compatibility adapter. Return riders cannot introduce unannounced targets. Another Round reselects per pass; entry counters combine through replacements. Paper observations are factual player reports; Alchemy remains a non-goal.
- **Baselines / artefacts:** PARSER_VERSION 667 and lock synchronized. Overall `/tmp/par157-modular-coverage.log`: 21626/35046 (61.7%); Commander-legal `/tmp/par157-modular-commander-coverage.log`: 20804/32068 (64.9%). Full-cache `/tmp/par157-modular-full-cache-final.log`; probe baseline `/tmp/par157-modular-base.json`, diff `/tmp/par157-modular-diff-final.log`. Cached candidate inventory including back text: `/tmp/par157-modular-family.json`; sampled residue: `/tmp/par157-resume-residue-audit.json`. Original 37-card matrix is absent; reconstruct the bounded family from these candidates and code/tests.
- **Known failures:** None in the final full-cache or focused gates.
- **Residue:** Shared pool write/transfer identity (including cost-exiled/Mechtitan links); exact crew/saddle event groups; branches based on pre-exile control; exile-zone trigger grants, counter/return choices and measured follow-ups (Cosima-shaped). Transformed-return grammar does not complete missing back-face behavior: `Card.back_face()` currently omits printed back loyalty/defense, and several sampled backs still have unclaimed abilities (including Liliana). Verify both reachable faces before claiming a complete transformed card. Finish the full bounded-family audit and close PAR-157 only when these shared capabilities and remaining compositions are verified.
