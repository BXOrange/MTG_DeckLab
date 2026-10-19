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

- **Started / last update:** 2026-10-16 / 2026-10-19
- **Goal of this run:** Finish the shared exile/return mechanism, including transformed entry and riders, using the same ordinary parser/binder for either face. Missing actions printed on a reachable face are separate parser/mechanic work, not a completion requirement for this ticket.
- **Done (built + tested):** Exact source/exile/graveyard visits, captured controller, immediate/delayed returns, shared entry batches and interactive entry data are built. Return receipts gate successful-return riders; counters, tapped/face data and original/new measurements stay distinct. Linked pools, repeated selection and group returns survive clone/undo. Both faces retain printed characteristics and native abilities; returning to the front rebinds front abilities. Durable implementation details and the additional shared body-grammar work already shipped are in `Done_Backend.md`.
- **In progress:** Worker implementation and acceptance checks complete; awaiting orchestrator review/commit/closure. Shared composition reuses existing group selectors and ordinary counter/tap/keyword riders; entry-controller checks retain the actual entry recipient. Three focused test modules prove ordinary front/back binding, successful-return riders and batch selection. No missing back-face action has been implemented.
- **Next step:** Orchestrator: review and commit the verified version-687 diff, then perform ticket closure and separate cross-game MEC planning. Ordinary selector/action/trigger grammar remains separate under PAR-132/PAR-166/PAR-167.
- **Decisions:** Front/back is an input/characteristic selection axis, not a separate action grammar. Transformation must bind the selected face through `bind_from_catalogue` / `card_registry.specs_for`; unknown face text keeps the ordinary fail-closed behavior. Do not make every reachable double-faced card fully modeled as a prerequisite for closing PAR-157. Existing parser/effect capabilities must compose; no card-name-specific runtime adapters. Paper observations remain explicit facts; Alchemy remains a non-goal.
- **Baselines / artefacts:** PARSER_VERSION 687 and lock synchronized. Isolated cache `/tmp/par157-cache/db/cards.db`; authoritative ledger `/tmp/par157-worker-687-coverage.db`. Coverage 21780/35046 (62.1%), Commander 20952/32068 (65.3%); `/tmp/par157-worker-687-{coverage,commander-coverage}.log`; status locales and parser coverage summary synchronized. Discovery scan: 374 candidate faces, classified in `/tmp/par157-mechanism-inventory687.json`; broad raw matches include unrelated reanimation/costs, authored handlers and ordinary grammar gaps. The inventory is evidence at clause level, not a whole-card modeling requirement. Prior committed implementation baseline: `ecc70e63`, version 685, 14670 passed / 1 skipped.
- **Known failures:** None in the focused worker gate: `/tmp/par157-worker-all-focused.log`, 501 passed. Pre-edit snapshot `/tmp/par157-worker-base685.json`; mechanism diff `/tmp/par157-worker-mechanism-diff.log`: +4 / -0. Version 687 focused gate: `/tmp/par157-worker-687-focused.log`, 505 passed. Snapshot `/tmp/par157-worker-base686.json` → `/tmp/par157-worker-687-diff.log`: +1 / -0; total +5 / -0 versus v685. Compatibility gate `/tmp/par157-worker-687-compatibility.log`: 539 passed, including legacy source/group parser assertions now checking the shared blink subject, timing and selector data. Required full-cache wrapper `/tmp/par157-worker-687-full-final.log`: 14695 passed, 1 skipped in 220.58s. `git diff --check` clean. Any still-unknown body/trigger grammar remains unmodeled.
- **Residue:** No known failing acceptance checks. Orchestrator review/commit/closure remains. Unmodeled face actions and ordinary selection/reference/trigger bodies remain with PAR-132/PAR-166/PAR-167, including opponent-recipient choices, linked-event bodies and owner-player schedule references. Entry-provenance selection should reuse existing `entered_via_ability_id` before proposing another mechanic. Time Machine's cross-game return state has no identified runtime primitive and needs independent MEC-ticket planning; it is not an extension of transformed-entry parsing. Worker leaves BACKLOG/Done and ticket closure to the orchestrator.

### Mechanism-only completion plan

| Step | Work | Acceptance evidence |
| --- | --- | --- |
| 1. Rebuild the bounded inventory | Scan current paper Oracle clauses for exile/return with entry or follow-up riders, plus transformed-return clauses. Separate source/target/pool, timing, controller, entry face/data and rider axes. Classify unrelated action/trigger gaps and non-goals explicitly. | Each relevant clause has a mechanism verdict and a test/reference; whole-card or whole-back `MODELED` is not the proxy. Keep raw inventories temporary; only verified scope decisions belong in project docs. |
| 2. Prove face-independent composition | Trace `flicker_sequences` → shared return/entry batch → face selection → ordinary `bind_from_catalogue`/`specs_for`. Check supported ordinary ability bodies on either face, transformed entry, copied/transformed objects and return to the front. | Focused runtime tests show the same supported bodies bind/execute on both faces, preserve printed characteristics and replace old-face abilities. An unsupported back action remains unmodeled without introducing a special back-face parser or silently claiming the missing mechanic. |
| 3. Close only mechanism defects | Reuse exact-visit captures, controller snapshots, schedules, entry choices and returned-object receipts. Extend a shared axis only when the inventory proves a gap in the mechanism itself. | Existing `test_par157_{rider_grammar,entry_data,return_visits,return_batches,return_variants,back_characteristics,modular_sequences,deferred_sequences,successful_return_riders}.py` plus narrowly necessary tests cover immediate/delayed timing, fresh visits, clone/undo, group entry, entry data and successful-return gating. Unknown compositions remain fail-closed. |
| 4. Verify and close | Run the focused mechanism matrix and required full-cache suite. If parser behavior changes, use a pre-edit probe snapshot, bump version/lock, require zero unintended regressions, remeasure coverage and sync status text. Review the actual final diff against this scope. | Required checks pass; no mechanism requirement remains unproven. Commit, remove PAR-157 from BACKLOG and this block, and retain the delivered mechanism summary in Done_Backend. PAR-166/PAR-167 stay open for independent implementation. |
