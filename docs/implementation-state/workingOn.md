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
- **Done (built + tested):** Shared blink subject/copy/exile/return phases, exact-visit linked pools, entry options and successful-return riders replace bespoke adapters. Searches, costs, multi-pick choices and crew/saddle events retain exact visits. Printed back loyalty/defense, Vehicle/Spacecraft P/T and per-face intrinsic keywords survive conversion/copy/materialization and verified offline cache migrations. Shared negative-X loyalty and captured death returns complete Liliana’s back; persistent zone grants, optional measured returns and filtered standing play permissions complete both Cosima faces. Departing source counters now use per-visit LKI instead of surviving on exiled cards.
- **In progress:** v672 adds structured group control and untargeted land selection through existing effects; both Azusa and Horobi faces execute (8 focused tests passed). Full-cache/probe/coverage gates are green; 17 reachable backs and the bounded-family audit remain. Production cache is unchanged (35095 rows, predecessor hash unchanged); isolated cache preserves all 35095 rows after compatible migration.
- **Next step:** Continue the remaining reachable-back compositions from `/tmp/par157-back-audit671-verified.json` (56 transformed-return candidates, 19 covered fronts with uncovered backs at v671; Azusa and Horobi resolved in v672). Size shared Saga chapter/flavor-label handling and target-free object-selection shapes (Azusa’s untap; Tribute to Horobi’s token control) before changing grammar; use the Rules-Wiki for flavor-word rules. Reuse existing selectors/choices/grants rather than enumerating card-specific adapters. Then close the other back compositions and complete the full bounded-family audit. Broad `/tmp/par157-family-current.json` includes unrelated plain blink/reanimation/non-goals and is not the acceptance boundary.
- **Decisions:** User explicitly requested generalization/modularity. Selection, measurements, timing, entry and follow-up instructions are separate axes; reuse bind/seq/choices/blink before adding any runtime type. Existing transformed-return spelling remains a compatibility adapter. Return riders cannot introduce unannounced targets. Another Round reselects per pass; entry counters combine through replacements. Paper observations are factual player reports; Alchemy remains a non-goal.
- **Baselines / artefacts:** PARSER_VERSION 672 and lock synchronized. v672 full-cache `/tmp/par157-672-full.log`: 14477 passed, 1 skipped; focused back selections: 8 passed. v672 probe +6 / -0 against `/tmp/par157-base671.json`; overall 21647/35046 (61.8%), Commander 20823/32068 (64.9%) in `/tmp/par157-672-{all,commander}-coverage.log`, ledger `/tmp/par157-672-coverage.db`. v671 evidence: Full-cache `/tmp/par157-671-full-verified.log`: 14469 passed, 1 skipped. Focused final fixes `/tmp/par157-671-final-fixes.log`: 57 passed (zone grants, back characteristics/migrations, LKI and selector regressions). Probe `/tmp/par157-base670-reconstructed.json` → `/tmp/par157-671-diff-verified.log`: +1 / -0 (Cosima); the baseline reconstructs v670’s verified +5/-0 covered set from v669. Authoritative `/tmp/par157-671-all-coverage-verified.log`: 21641/35046 (61.8%); `/tmp/par157-671-commander-coverage-verified.log`: 20818/32068 (64.9%). Isolated cache `/tmp/par157-cache/db/cards.db`, ledger `/tmp/par157-671-coverage.db`; pre-migration backup `/tmp/par157-cache-before671.db`. Original 37-card matrix is absent; reconstruct the bounded family from candidates and code/tests.
- **Known failures:** None in final v672 full-cache gate. Local-network tests need execution permission for localhost. Lost Isle Calling’s departed-counter reads and live “other” selector identity are covered by the final regression gate.
- **Residue:** 17 still-uncovered reachable backs: Ajani, Huatli, Jace, Jecht, Jill, Jin-Gitaxias, Joshua, Nicol Bolas, Nissa, Ral, Sorin, Tamiyo, Teachings of the Kirin, The Kami War, The Legend of Kuruk, Urabrask and Vorinclex (exact clauses in `/tmp/par157-back-audit671-verified.json`). Liliana and both Cosima faces are finished; no exile-zone grant or measured-return residue remains for Cosima. Verify both reachable faces and complete the bounded-family audit, including genuine rider compositions outside the back-face list, before closing PAR-157.
