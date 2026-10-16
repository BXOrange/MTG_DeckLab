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

## PAR-156 · Counter or pump, then fight

- **Started / last update:** 2026-10-16 / 2026-10-16
- **Goal of this run:** Complete the connected buff/counter-before-fight family, including verified composite residue.
- **Done (built + tested):** Parser v663 shared sequences and linked/reflexive follow-ups support 17 previously uncovered paper-family cards; Ancient Animus was already authored, Algorithmic Ferocity is an explicit Alchemy non-goal. Directed fight receipts preserve actual excess/hit sets across replacement choices, clone/undo and concession. Conditions affect only the friendly bonus; permanent Host/Augment bonuses and original target groups are retained. Full backend --full-cache: 14,097 passed, 1 skipped (/tmp/par156-repaired-root-full.log); 61 family tests and 265 broader focused tests passed. Cache comparison +19/-0 includes two verified collateral cards.
- **In progress:** Verified backend milestone ready for commit; Alexander remains pending MEC-123.
- **Next step:** Deliver MEC-123 backend and real Alexander casting/reveal behavior, then audit the complete PAR-156 matrix and close separately.
- **Decisions:** No silent scope reduction: Ace/Gimli/Kraul/Rhino/Fight for the Throne are delivered; Alexander stays explicit residue. Group effects survive source departure; only true self/fight instructions reject later source incarnations. One-sided source damage retains legal last-known information.
- **Baselines / artefacts:** Original v662 from f7ee7bdb reconstructed /tmp/par156-before.json; final v663 probe /tmp/par156-worker-probe.log. Authoritative v663 coverage 21,591/35,046 (61.6%); Commander 20,773/32,068 (64.8%). MEC-123 baseline /tmp/mec123-before.json.
- **Known failures:** None after repair and final full-cache run.
- **Residue:** MEC-123 physical printed-line behavior for Alexander; final combined scope audit and close-out commit. PAR-156 remains open.

## MEC-123 · Physical printed rules-text line measurements

- **Started / last update:** 2026-10-16 / 2026-10-16
- **Goal of this run:** Printing/face-specific factual measurements for actual Alexander wordy casting and reveal/pump/fight, with usable UI and no Card fields.
- **Done (built + tested):** Frontend milestone 58a5a53c: strict numeric fact form, readable printing/face, localized instructions and normal choice submission. Independent real-browser UI fixture passed (/tmp/mec123-root-ui-final.log); actual backend integration remains unverified. Architecture /tmp/mec123-architecture-plan.md and /tmp/par156-alexander-plan.md.
- **In progress:** Frontend committed and frozen. Backend integration waits for PAR-156 source release.
- **Next step:** After PAR-156 backend release, deliver state-owned facts, pre-cast announcement and revealed-card operand using the committed UI contract below; verify real Alexander behavior, privacy, continuation tests and actual backend/browser flow.
- **Decisions:** Choice kind `physical_property_measurement`, property `printed_rules_lines`, integer minimum 0, maximum supplied by backend `maximum`; subject fields `printing_id`, optional human-readable `printing_label`, `face`, `name`, `image_url` visible only to authorized decider. Submit ordinary choose action with decimal-string option_id. Unknown is not zero; no default/clamping or Oracle line estimate. Shared pending prompt must be generic to avoid private-hand leaks.
- **Baselines / artefacts:** v662, f7ee7bdb; PAR-156 backend in progress. Source facts follow exact printing/face, not card name.
- **Known failures:** No known frontend fixture failures. Core measurement/casting/reveal behavior is not implemented yet.
- **Residue:** Core measurement and casting integration, live Alexander behavior, privacy/controlled-turn/undo/concession tests, independent full-cache/browsers/coverage and separate commit.
