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

## PAR-177 · Context-aware gap catalogue and joint-fix ranking

- **Started / last update:** 2026-10-21 / 2026-10-21
- **Goal of this run:** Complete the full-pool context graph and prerequisite-aware ranking.
- **Done (built + tested):** `parser/gap_catalogue.py` retains unresolved occurrence identity, modal collateral and opaque blockers; probe rank consumes graph and offers joint packages. Fifteen focused regressions pass, including A+B/B+C/C+D, large cyclic prerequisites, modal collateral and unsupported heads, shared roles, Room face/card uniqueness, authoritative occurrence audit, minimal spans and CLI span/line distinction. Full-pool span smoke: 35,095 cards, 11,938 uncovered cards, 14,855 unresolved occurrences; no parser verdict changes.
- **In progress:** Full-pool joint CLI smoke with authoritative audit; orchestrator independent verification.
- **Next step:** Poll exec session 44202 and inspect `/tmp/par177-joint-full.txt`; orchestrator owns complete-suite validation and closure.
- **Decisions:** Diagnostic capability packages estimate grammar repairs; opaque blockers cannot be selected as repairs. Complete card packages survive package-size exploration bounds; candidate-budget truncation is explicit.
- **Baselines / artefacts:** `/tmp/par177-rank.txt`, `/tmp/par177-joint-full.txt`; parser verdicts unchanged, no version bump.
- **Known failures:** None in focused tests.
- **Residue:** Full-pool joint CLI completion and independent review pending; implementation complete.

## PAR-182 · Attached-host upkeep heads and body references

- **Started / last update:** 2026-10-21 / 2026-10-21 21:37
- **Goal of this run:** Shared attached-host step heads and attached counter recipients with real gameplay verification.
- **Done (built + tested):** Shared phase head reuses live host-controller relation; counter recipient axis supports explicit enchanted host and contextual “that creature”; phase damage inside immediate bind/seq/if_else resolves the step player. Existing engine primitives reused. 12 new tests; 44 focused tests pass (test_par182_attached_upkeep.py, test_phase_and_damage_triggers.py, test_par117_attached_permanent_controller.py).
- **In progress:** Ready for orchestrator independent verification and final coverage/version update.
- **Next step:** Root full suite/full-cache and authoritative measurement, then ticket closure.
- **Decisions:** Existing source departure preserves attachment for RULE 608.2h; tested source destruction, host destruction, detach and reattach while stacked, unrelated upkeep and controller changes. Future granted triggers are excluded from phase damage rewrite.
- **Baselines / artefacts:** /tmp/par182-base.json (21852/35095 v716); /tmp/par182-family.json. Full shared host-head family: 30 cards, 2 authored, 14 new parser gains, 14 remain blocked by unrelated bodies. Combined parallel probe diff +37/-0 before last selector correctness correction; 27 own gains (14 heads, 13 explicit counter bodies) plus 10 concurrent energy gains. Spot-checked Biting Tether, Krovikan Plague, Glistening Oil and all gained host-head specs.
- **Known failures:** None in final focused tests. Root owns complete suite.
- **Residue:** No implementation residue for this ticket. Family bodies still unsupported: Apathy, Curse Artifact, Erosion, Errant Minion, Mind Whip, Paralyze, Paroxysm, Power Leak, Power Taint, Slow Motion, Soul Tithe, Takklemaggot, Unnatural Hunger, Venarian Gold (not promised unlocks).

## PAR-178 · Optional-payment continuations: referents and announced targets

- **Started / last update:** 2026-10-21 / 2026-10-21
- **Goal of this run:** Complete source-referent and announced-target energy payoffs for the five assigned cards.
- **Done (built + tested):** Shared payment wrapper preserves ClauseReading and announced target; GameState energy continuation retains firing event, references, controller and source incarnation across clone/undo. Atomic decline guard prevents connector fallback from ungating unsupported branches. 78 focused/adjacent tests pass, including all five cards and bonus Assaultron firing-object continuation.
- **In progress:** Independent orchestrator verification and closure.
- **Next step:** Orchestrator completes full-suite/full-cache verification, version/coverage updates and ticket closure.
- **Decisions:** Reuse pay_energy_then; targeted reflexive “when you do” and independent target groups remain fail-closed. Wrapper-owned existing target (Confiscation Coup) is announced only once.
- **Baselines / artefacts:** `/tmp/par178-base.json`, v716 baseline 21852/35095; `/tmp/par178-final-diff.txt` +42/-0 across concurrent PAR-178/179/182 tree; ten energy-family gains include all five assigned cards.
- **Known failures:** None in 78 focused/adjacent tests.
- **Residue:** No assigned implementation residue; independent complete-suite/full-cache validation pending.

## PAR-180 · Library selection and follow-up composition

- **Started / last update:** 2026-10-21 / 2026-10-21 21:43
- **Goal of this run:** Complete named-card reveal searches and look/pick/rest sequences including removed-counter X and DFC faces.
- **Done (built + tested):** Inspected all six named cards; existing search, bounded inspect and look_top_select order primitives identified.
- **In progress:** Family sizing; shared grammar axes and missing bounded-inspect graveyard action.
- **Next step:** Widen existing grammar, exercise full choices and order in engine tests.
- **Decisions:** Reuse search, look_top_select and inspect_top_choose; retain serialized selected-pool choices.
- **Baselines / artefacts:** /tmp/par-all-base.json v716; family blocked probe running.
- **Known failures:** None yet.
- **Residue:** Implementation and verification pending.

## PAR-179 · Exiled-source land grants and casting permission

- **Started / last update:** 2026-10-21 / 2026-10-21
- **Goal of this run:** Compose hand-exile costs, quoted grants and independently scoped exile casting permission.
- **Done (built + tested):** Normal stack activation now pays source-from-hand exile costs; activation event preserves exact cost-created exile visit. Existing `GrantUntilEffect`/mana-grant primitives carry an until-source-cast duration; cast completion ends only matching visits after mana payment. Standing permission uses existing visit-keyed bookkeeping. Parser row composes quoted grants and permission, preserving one target for compound quotes. Runtime tests cover five real cards, Spara's remaining restriction, actual casting/mana, source and land exits/reentries, target fizzle, cleanup, clone and session rewind.
- **In progress:** Focused compatibility suites and independent verification.
- **Next step:** Orchestrator run aggregate probe diff from `/tmp/par-all-base.json`, complete suites and independent review; inspect `tests/test_par179_exiled_source_grants.py` for ticket acceptance.
- **Decisions:** Land grant survives unrelated source exile exits; only casting the exact cost-created exile incarnation ends it. Permission ends when that visit ends. RULE 400.7j and 611.2a/b; official SNC release notes confirm grants remain after unrelated exit and can pay for the source spell.
- **Baselines / artefacts:** `/tmp/par179-sizing.log`, `/tmp/par179-card.txt`, `/tmp/par-all-base.json`; root owns parser-version bump and authoritative coverage.
- **Known failures:** None in ticket regressions.
- **Residue:** Aggregate regression/coverage checks and independent verification; implementation complete.
