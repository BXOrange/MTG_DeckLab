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

## PLR-9d · Administration

- **Started / last update:** 2026-11-04 / 2026-11-04 (loopback admin committed; parked on MFA decision)
- **Goal of this run:** full PLR-9d per plan §6 and §8 Admin/Initial setup/Admin invitations gates, except MFA (method is a user decision; remote admin stays disabled).
- **Done (built + tested):** (suite 18717 passed, 489 skipped; Playwright against a `--localdev` temp data dir: setup flow, XSS names as text, disable/delete, global deck, job + poll, player session denied on /api/admin, no cookie/storage) `services/account_store.py` (migration 2: meta/audit_log/recovery_credentials; seed_initial_admin, complete_setup, list_players, audit, recovery), `api/admin_auth.py` (Basic per request, identity throttle, loopback gate, online disabled), `api/admin.py`, `services/admin_jobs.py`, `services/admin_service.py` (delete cascade), sweeper frees deleted seats, `frontend/admin/*` page, proxy gate + CSP for `/admin`, `manage_accounts.py recover`, `/api/auth/recover`.
- **In progress:** nothing.
- **Next step:** PARKED on user decision: MFA method for remote admin. Then build MFA enrolment/recovery codes, the `--online` first-admin path and the player recover form. Deletion-journal question moved to PLR-9e.
- **Decisions:** credentials = `Authorization: Basic` (UTF-8) per request, page keeps them in memory only, drops on logout / 5 min idle, destructive actions re-ask the password; poll token adopted as the plan proposes (job-bound, digest only, valid until the job is evicted 1 h after it ended); `--online` disables the whole admin surface (403 `admin_disabled`) because MFA is undecided; initial admin seeded at app startup (lifespan) once, `meta` flag prevents reseed even after the account is gone; delete confirmation = exact name typed plus password re-entry in the page; no deletion-journal replay.
- **Baselines / artefacts:** backend suite green at b0062bfd (18614 passed, 489 skipped).
- **Known failures (corrected; final full-cache recheck pending):** none.
- **Residue:** open user decision: MFA method (e.g. TOTP + recovery codes) for remote admin (until then the whole admin surface is disabled in `--online` and no OS-operator command creates a first `--online` admin); open decision for 9e: deletion journal replay after a backup restore (only a SERVER_GUIDE caveat now); player-UI form for `POST /api/auth/recover` not built (API + admin page form + CLI exist).

## PLR-17 · Protect admin/server routes

- **Started / last update:** 2026-11-04 / 2026-11-04 (update routes committed; parked on MCP-token decision)
- **Goal of this run:** allowlisted DB refresh/update routes admin-only (via PLR-9d admin auth), player/anonymous denied even by direct call; LLM settings/tests OS-operator only.
- **Done (built + tested):** `POST /api/cards/update` and `POST /api/combos/update` depend on `api/admin_auth.require_admin`; the player "Einstellungen" update buttons point to `/admin`. Tests: `tests/api/test_api_admin.py::TestUpdateRoutesEnforcement` (anonymous / player cookie / player password / LAN client denied, admin allowed, route-inventory guard).
- **In progress:** nothing.
- **Next step:** PARKED on user decision: how `/api/mcp-settings/{setup,rotate}` should be protected without breaking the Einstellungen MCP setup UI (admin-only via /admin, loopback+login, or OS-operator CLI only).
- **Decisions:** the ticket's LLM routes (`/api/llm/*`, narrative analysis, LLM bots) do not exist in this tree (only in a stale worktree under `.claude/worktrees/`), so there is nothing to protect there; a route-inventory test guards against new unlisted update routes and any `llm` route appearing unprotected.
- **Baselines / artefacts:** backend suite green at b0062bfd (18614 passed, 489 skipped).
- **Known failures (corrected; final full-cache recheck pending):** none.
- **Residue:** LLM settings/test routes: none exist in this tree, so the OS-operator mechanism was not needed; if LLM features return, decide the operator channel then (the plan names none). Question for the user: `/api/mcp-settings/{setup,rotate}` hand out / rotate the persistent MCP server token to any caller (server operation, outside the ticket's named list).
