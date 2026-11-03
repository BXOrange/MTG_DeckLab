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

## PLR-9a · Run modes, account storage and authentication

- **Started / last update:** 2026-11-03 / 2026-11-03
- **Goal of this run:** build PLR-9a bottom-up on `feature/PLR-9`; nothing reaches `main` before the PLR-9e cutover (plan §2, no feature flag).
- **Done (built + tested):**
  - Storage/crypto: `config.py` "Accounts (PLR-9a)" constants; `services/password_policy.py` (red/yellow/green; blocklist `data/common_passwords.txt` is a placeholder); `services/password_hasher.py` (scrypt, rehash-aware); `services/account_store.py` (`accounts.db`, versioned migrations, accounts/sessions/invitations/tombstones, atomic invite redemption); `services/rate_limiter.py`; tests `tests/services/test_account_store.py`.
  - API: `api/auth.py` (`/api/auth`: policy, me, signup by invitation, login with generic failures + `dummy_verify` + per-source/per-name throttle, logout, logout-all, password-change, player invitations create/list/revoke; `current_context`/`current_account` enforce `X-CSRF-Token` on cookie-bearing unsafe requests; cookie `mtg_session` HttpOnly/Lax, `__Host-` + Secure when `RUN_MODE=online`); `tests/api/test_api_auth.py`.
  - Run modes: `services/network_gate.py` + peer gate in `request_guard` (only when `MTG_RUN_MODE` is set explicitly, i.e. by `start.py`; fail-closed to loopback); `start.py --lan/--online/--localdev/--allow-network/--tls-cert/--tls-key/--behind-tls-proxy` (`resolve_run_mode`; no flag = legacy behaviour until 9e); default-localuser auto-session (localdev + `is_local_request` + opt-out cookie on logout); tests `test_network_gate.py`, `test_start_run_modes.py`.
  - Frontend: `auth.js` (`apiFetch` with credentials + CSRF header, used by all `api.js` requests and bugReport), `passwordStrength.js`, `accountView.js` (login, invitation signup incl. `#invite=` fragment, password change, invitations, meter: red blocks submit, yellow does not), Profil panel + header chip, `account.css`, DE/EN `account.*` keys, CORS `allow_credentials` (loopback regex only). Verified in Chromium against a `--localdev` backend.
  - Ops/docs: `backend/scripts/manage_accounts.py invite|list` (OS-operator first invitation, `tests/test_manage_accounts_script.py`); `psutil` in `requirements.txt`; `start.sh`/`start.bat`/`start.py`/`install.py` text; `docs/Reference/SERVER_GUIDE.md`; OPERATIONS/README pointers.
- **In progress:** —
- **Next step:** close out the residue below, then close 9a (Done_Backend/Done_Frontend entries, delete this block, trim BACKLOG). Start PLR-9b only after that.
- **Decisions:** legacy start (no mode flag) stays until 9e flips it; scrypt default since `argon2-cffi` is not installed; `psutil` added to requirements (LAN subnet auto-detection; without it loopback only, `--allow-network` still works); `frontend_proxy` is backend→frontend so it does not hide client addresses.
- **Baselines / artefacts:** full backend suite green after the storage layer (18447 passed); re-run after frontend/ops: 18497 passed.
- **Known failures (corrected; final full-cache recheck pending):** none; full backend suite green (18497 passed, 489 skipped) after the frontend/ops work.
- **Residue:** (1) `request_guard` CSRF rule: a cookie-bearing unsafe request must carry the token even with neither `Origin` nor `Sec-Fetch-Site` — only routes using `current_context` (`/api/auth`) enforce it today; 9b wires the rest, decide whether the guard should do it centrally; (2) active-sessions list in the UI (plan §3); (3) compromised-password blocklist source/size/licence; (4) Argon2id vs scrypt decision with measurements; (5) pre-login CSRF context for login/signup is covered by Origin checks only; (6) `psutil` wheel in a shipped wheelhouse for offline installs.
