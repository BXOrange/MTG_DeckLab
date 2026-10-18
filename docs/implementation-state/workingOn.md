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

- **Started / last update:** 2026-10-16 / 2026-10-18
- **Goal of this run:** Generalize the remaining flicker work as shared subject/capture, exile-phase, copy-recipient, timing, entry and successful-return axes; migrate bespoke adapters instead of adding card-specific runtime types.
- **Done (built + tested):** Shared blink subject/copy/exile/return phases, exact-visit linked pools, entry options and successful-return riders replace bespoke adapters. Searches, costs, multi-pick choices and crew/saddle events retain exact visits. Printed back loyalty/defense, Vehicle/Spacecraft P/T and per-face intrinsic keywords survive conversion/copy/materialization and verified offline cache migrations. Shared negative-X loyalty and captured death returns complete Liliana’s back; persistent zone grants, optional measured returns and filtered standing play permissions complete both Cosima faces. Departing source counters now use per-visit LKI instead of surviving on exiled cards. Shared group control/land choices complete Azusa and Horobi backs. Saga flavor-label normalization, omitted return recipients and source-pronoun captures complete Jecht and Jill; coordinated player verbs preserve group scope (Anima). Deferred whole-blink timing completes Galleon’s front-to-back transition; Crew animation and delayed self captures retain the original visit. Aggregate mana/power target limits cover counts, scopes and subtypes across spells, activations, triggers, copies and board metadata. Partial trigger announcements live in GameState for clone/undo. Multiple targeted graveyard returns share exact simultaneous entry batches, including entry choices before Joshua’s return to the front. Source-granted quoted abilities, nested quotes, N-way mana options and shared subtype searches complete Huatli. Printed Changeling and unconditional subtype CDAs use a shared model vocabulary; explicit permanent restrictions and other card-type filters remain independent. Targeted normal-cost graveyard grants and optional spell-zone exile replacements complete Jace’s back, with exact visits, cleanup, clone, cross-turn resolution and bounce/recast coverage. Shared previous-target animation and comma-bearing printed legendary token names complete Nissa’s back; permanent grants retain exact visits and modal token names retain original spelling. Existing library-slice and graveyard-union primitives complete Nicol Bolas’s back: owner/target, edge, removal/retention count and face-down grammar compose without a new runtime effect.
- **In progress:** No unfinished edit in v680; full-cache/probe/coverage gates are green. Ten previously identified reachable backs and the bounded-family audit remain.
- **Next step:** Continue reachable-back compositions from `/tmp/par157-back-audit680-verified.json`. Teachings of the Kirin’s back needs successful targeted exile → reflexive body composition for both modes; inspect the shared optional-exile/reflexive primitives (`segmenter._MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE`, `may_exile_source_then`) and movement-result composition before adding a runtime type. Announce reflexive targets only after successful exile. Then finish the other reachable backs and bounded-family audit; the broad candidate pool is not the acceptance boundary.
- **Decisions:** User explicitly requested generalization/modularity. Selection, measurements, timing, entry and follow-up instructions are separate axes; reuse bind/seq/choices/blink before adding any runtime type. Existing transformed-return spelling remains a compatibility adapter. Return riders cannot introduce unannounced targets. Another Round reselects per pass; entry counters combine through replacements. Paper observations are factual player reports; Alchemy remains a non-goal.
- **Baselines / artefacts:** PARSER_VERSION 680 and lock synchronized. Full-cache `/tmp/par157-680-full.log`: 14608 passed, 1 skipped. Final focused/version-pin `/tmp/par157-bolas-final-pin.log`: 21 passed after behavior-neutral definition/comment placement cleanup. Probe `/tmp/par157-base679.json` → `/tmp/par157-680-diff.log`: +6 / -0. Authoritative `/tmp/par157-680-all-coverage.log`: 21711/35046 (62.0%); `/tmp/par157-680-commander-coverage.log`: 20885/32068 (65.1%). Isolated cache `/tmp/par157-cache/db/cards.db`, ledger `/tmp/par157-680-coverage.db`. Back audit `/tmp/par157-back-audit680-verified.json`: 56 candidates, 10 covered fronts with uncovered backs (includes authored front registrations, notably Ral). Original 37-card matrix and old scope files are absent, including in their historical `/tmp` paths. Broad family residue `/tmp/par157-family-residue673.json` contains 159 historical candidates, including unrelated reanimation/plain blink/non-goals; recheck against current source and reconstruct the bounded family from raw text and code/tests.
- **Known failures:** None in final v680. Local-network tests require localhost execution permission.
- **Residue:** 10 still-uncovered reachable backs: Ajani, Jin-Gitaxias, Ral, Sorin, Tamiyo, Teachings of the Kirin, The Kami War, The Legend of Kuruk, Urabrask and Vorinclex (exact clauses in `/tmp/par157-back-audit680-verified.json`). Nicol Bolas, Nissa, Jace, Liliana and both Cosima faces are finished; no exile-zone grant or measured-return residue remains for Cosima. Verify both reachable faces and complete the bounded-family audit, including genuine rider compositions outside the back-face list, before closing PAR-157.
