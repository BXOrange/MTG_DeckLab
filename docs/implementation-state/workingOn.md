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

---

## PLAY-ALL · Make every saved deck playable

- **Goal:** Bring every non-cube saved deck to N/N and close all originally recorded correctness gaps and parser follow-ups. Commander Cube remains optional; moving work into tickets does not reduce this goal's scope.
- **Branch / committed baseline:** `Backlog-Extension`; latest commit `3a96336c` (ticket scoping), preceded by `f91f5eed` (Burn Away, v626) and `143c3d09` (Searing Blood, v625). Current implementation below is uncommitted; inspect `git status` and the diff before continuing.
- **Next step:** Validate the current MEC-116/Fatal Fissure changes broadly and compare parser v627 against `backend/.pytest_cache/parser-v626-base.json`. Fix regressions, measure authoritative total and Commander coverage, update the four coverage documents, remove stale Earthbend simplification descriptions, then commit. Continue the remaining PAR-154 cards and MEC-115 afterward; retain the other parser axes below.
- **In progress — MEC-116 / Fatal Fissure:** `handlers.py` accepts "you earthbend N"; parser and generated version lock are v627. `RulesEngine.earthbend` creates a persistent one-shot return on `LEAVES_BATTLEFIELD`, constrained to death/exile and the captured battlefield incarnation. It returns tapped under the original bender's control, survives later turns/source-control changes, and is removed after triggering or invalidation. Turn-trigger collection also excludes departed controllers.
- **Changed infrastructure:** `game_state.py` allows `TurnScopedTrigger.install_turn=None` and stores optional bound-object identity/incarnation; `triggers_mixin.py` handles persistence and invalidation. `damage_death_mixin.py` snapshots pre-move incarnation for graveyard/exile leaving events. `continuous.py` honors `object_incarnations` for scoped animations. `counters_tokens.py` guards trigger-subject returns against changed zones/incarnations and tokens. `choices_actions.py` passes the resolving controller to Earthbend. These shared changes require broad regression validation.
- **Current tests:** 89 passed with the command below. New `tests/test_earthbend_return.py` covers death/exile returns, later turns and source control changes, legal bounce/replay of a land, real Stifle, another graveyard incarnation, state cloning, Earthbend zero, departed controllers, and Fatal Fissure's resolution-time trigger target announcement. No known focused failures. No v627 full-suite or coverage job has been started; no validation job needs to be resumed.
- **Validation commands (cwd `backend`, Windows):** Use `./venv_win/Scripts/python.exe` directly; this environment requires sandbox escalation to launch its Store-based Python. Focused: `-m pytest -q tests/test_earthbend_return.py tests/test_par29_earthbend.py tests/test_par30_earthbend_dynamic.py tests/test_par30_earthbend_when_you_do.py tests/test_dies_this_turn_pinned_family.py tests/test_trigger_controller_graveyard_exile.py tests/test_par124_turn_scoped_triggers.py tests/test_eng47_turn_trigger_sentences.py`. Broad: `-m pytest -q --full-cache --timeout=120` (20 seconds caused Windows bot-test timeouts). Parser diff: `-X utf8 ../.claude/skills/extend-parser/scripts/parser_probe.py diff .pytest_cache/parser-v626-base.json`. Measurements: `-X utf8 scripts/coverage_report.py --top 40` and `--commander-legal-only --top 40`. Regenerate the lock after parser edits with `scripts/update_parser_version_lock.py`; bump again if changing handlers after measuring that version.
- **Verified baseline:** Last complete backend/full-cache suite: 12,935 passed at v626. Last authoritative coverage: 21,047/35,046 (60.1%); Commander-legal 20,272/32,068 (63.2%). All 41 saved decks were rechecked after offline cache reseeding: every non-cube deck N/N, no unresolved names. Optional Commander Cube: 570/749. These are baseline values, not v627 measurements.
- **Documentation / tickets:** MEC-116 is open in `BACKLOG.md`; its implementation is built and focused-tested but not broadly validated or closed. PAR-154 covers the six named cards; MEC-115 is the Flip-card prerequisite for Initiate. Remove completed tickets only after their scope is verified, and document shared results in `Done_Backend.md`. Keep `workingOn.md` limited to the current resumable state. Coverage must be synchronized in `CLAUDE.md`, `PARSER_LONG_TAIL.md`, `status.de.js` and `status.en.js`.
- **Push:** Earlier automatic approval review rejected pushing because concrete-payload authorization and trusted destination ownership were considered insufficient. Confirmation was requested but no explicit answer has arrived. Do not bypass that rejection. Intended remote is `https://github.com/BXOrange/MTG_DeckLab`, branch `Backlog-Extension`; recheck the actual remote before publishing.
- **Decisions:** Prefer deck-by-deck work and reusable primitives; hand-author isolated gaps. Alchemy is a permanent non-goal. MODELED/AUTHORED coverage alone does not prove rules-exact behavior. RULE 701.66a explicitly returns the land under the bender's control; do not substitute its owner's control or a two-sided transform for RULE 710 flipping.

### Remaining required scope

- Complete MEC-116/Fatal Fissure validation and close-out.
- PAR-154: Reincarnation, Rushed Rebirth, Time to Feed, Sandals of Abdallah, Initiate of Blood; Initiate requires MEC-115. Recheck delayed target/source incarnation handling before claiming these correct.
- Broader mana-ability counter riders.
- Counter/pump-then-fight.
- Flicker with riders.
- Multi-event attack/block/target heads.
- Equipped-creature X pump.

Remove this block only after all remaining required scope has been implemented and verified. Commit and push after successful tests, subject to the outstanding push approval.
