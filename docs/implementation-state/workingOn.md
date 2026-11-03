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
- **Commit every iteration** (each green milestone: sub-step built + tested), not only at
  ticket close; update the block first so the commit carries the current state. Stage only
  your own files (see the shared-tree note in memory), never `git stash`.
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
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```

## REL-1 · Pin backend dependencies with hashes (formerly BUG-45b)

- **Started / last update:** 2026-11-02 / 2026-11-02
- **Goal of this run:** (a) LLM `base_url` SSRF guard and (c) bug reports for a multiplayer session only from a seat of that table with the lobby secret. (b) is not part of this run (see Residue).
- **Done (built + tested):** (c) `api/bug_reports.py` `_require_seat_at_table` + `player_id` body field + `X-Player-Secret`; `bugReport.js` sends identity; tests in test_api_multiplayer.py (`TestBugReportTableAccess`) and test_api_solo.py; BUG_REPORTS.md note. Full suite 18242 passed, 489 skipped. Browser check done. (a) moot, see Decisions.
- **In progress:** — (parked on the user decision below; (a) and (c) are closed and filed in Done_Backend.md)
- **Next step:** user picks the lock tool and whether `setup/install.py` installs from the lock (see Residue); then generate the lock per that choice and test an install from it, including the offline wheelhouse path.
- **Decisions:** (a) no code exists: the LLM integration (api/llm.py, llm_client.py, llm_settings.py) was removed in cb09a584, so there is no `base_url` to guard; nothing built. Stale git-ignored `backend/data/llm_settings.json` still holds an API key (user may delete). (c) non-seated/observer/unknown/lost-table -> 403 (not a stateless report); only MULTIPLAYER non-solo sessions are gated.
- **Baselines / artefacts:** full suite at 55639117: 18235 passed, 489 skipped.
- **Known failures (corrected; final full-cache recheck pending):** —
- **Residue:** (b) needs a user decision, do not implement unasked: hash pins with `--require-hashes` must cover the full transitive closure for every platform/Python the project installs on (macOS `venv`, Windows `venv_win`, offline wheelhouse from `--download-wheels`). A `pip freeze` from this Mac would pin platform-only packages (e.g. `uvloop` via `uvicorn[standard]`) and break Windows installs. Open question for the user: which lock tool (pip-tools `pip-compile --generate-hashes` per platform, or `uv pip compile --universal`), and whether `setup/install.py` switches to the lock file.
