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
- **Next step:** PAR-154 and MEC-115 are closed (parser v629: 21,075/35,046 = 60.1%, Commander-legal 20,300/32,068 = 63.3%; docs synced; `Done_Backend.md` filed). Continue with the remaining required scope below, starting with broader mana-ability counter riders. Baseline for diffs: take a `parser_probe.py` snapshot at v629 first.
- **Validation commands (cwd `backend`, Windows):** Use `./venv_win/Scripts/python.exe` directly. Broad: `-m pytest -q --full-cache --timeout=120` (~12 min). Parser diff: `-X utf8 ../.claude/skills/extend-parser/scripts/parser_probe.py diff <snapshot>`. Measurements: `-X utf8 scripts/coverage_report.py --top 40` and `--commander-legal-only --top 40`. Regenerate the lock after parser edits with `scripts/update_parser_version_lock.py`.
- **Verified baseline:** All 41 saved decks rechecked: every non-cube deck N/N. Optional Commander Cube: 570/749.
- **Documentation / tickets:** PAR-154 covers the five remaining named cards; MEC-115 is the Flip-card prerequisite for Initiate. Coverage must be synchronized in `CLAUDE.md`, `PARSER_LONG_TAIL.md`, `status.de.js` and `status.en.js`.
- **Push:** Earlier automatic approval review rejected pushing; no explicit user answer. Do not bypass. Intended remote `https://github.com/BXOrange/MTG_DeckLab`, branch `Backlog-Extension`; recheck the actual remote before publishing.
- **Decisions:** Prefer deck-by-deck work and reusable primitives; hand-author isolated gaps. Alchemy is a permanent non-goal. MODELED/AUTHORED coverage alone does not prove rules-exact behavior. RULE 701.66a explicitly returns the land under the bender's control; do not substitute its owner's control or a two-sided transform for RULE 710 flipping.

### Remaining required scope

- Broader mana-ability counter riders.
- Counter/pump-then-fight.
- Flicker with riders.
- Multi-event attack/block/target heads.
- Equipped-creature X pump.

Remove this block only after all remaining required scope has been implemented and verified. Commit and push after successful tests, subject to the outstanding push approval.
