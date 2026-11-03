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
- **Next step:** frontend login/signup slice: `GET /api/auth/policy` for the meter, red/yellow/green with missing-recommendation labels (red blocks submit), signup with invitation field (also from URL fragment), login, logout, password change, invitation create/list/revoke UI in Profil; `api.js` sends `X-CSRF-Token` from `/api/auth/me` and `credentials`; localized DE/EN via `i18n.js`; verify in a real browser (Playwright in `backend/venv`). Then close 9a: Done_Backend/Done_Frontend, delete this block, trim BACKLOG; docs/startup default flip stays for 9e.
- **Decisions:** legacy start (no mode flag) is unchanged until 9e flips it; `psutil` is not installed, so LAN auto-detection is loopback-only until it is added as a dependency (decide at 9e; `MTG_ALLOWED_NETWORKS`/`--allow-network` works without it); frontend_proxy is backend→frontend so it does not hide client addresses. <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```


## PLR-9a · Run modes, account storage and authentication

- **Started / last update:** 2026-11-03 / 2026-11-03
- **Goal of this run:** build PLR-9a bottom-up on `feature/PLR-9`; nothing reaches `main` before the PLR-9e cutover (plan §2, no feature flag).
- **Done (built + tested):** config constants (`config.py`, "Accounts (PLR-9a)"); `services/password_policy.py` (red/yellow/green, blocklist `data/common_passwords.txt` is a tiny placeholder); `services/password_hasher.py` (scrypt, rehash-aware); `services/account_store.py` (`accounts.db`, versioned migrations, accounts/sessions/invitations/tombstones, atomic invite redemption); `tests/services/test_account_store.py` (27 green); `services/rate_limiter.py` (sliding-window failure limiter); `api/auth.py` (`/api/auth`: policy, me, signup-by-invitation, login with generic failures + dummy_verify + per-source/per-name throttle, logout, logout-all, password-change, player invitations create/list/revoke; `current_context`/`current_account` dependency enforcing `X-CSRF-Token` on cookie-bearing unsafe requests; cookie `mtg_session` HttpOnly/Lax, `__Host-` + Secure when `RUN_MODE=online`); `config.RUN_MODE` + throttle constants; `tests/api/test_api_auth.py` (16 green); `tests/api` 319 green; `services/network_gate.py` + request_guard peer gate (active only when `MTG_RUN_MODE` is set explicitly, i.e. by `start.py --lan/--online/--localdev`; fail-closed to loopback without psutil), `tests/services/test_network_gate.py`; `start.py` flags `--lan --online --localdev --allow-network --tls-cert/--tls-key/--behind-tls-proxy` (`resolve_run_mode`; no flag = legacy behaviour until 9e); default-localuser auto-session in `api/auth.py` (localdev + `is_local_request` + opt-out cookie on logout), `AccountStore.ensure_default_local`.
- **In progress:** —
- **Next step:** (1) request_guard: peer-address allowlist (`MTG_ALLOWED_NETWORKS`, fail-closed to loopback, IPv6 unmapping, invalid CIDR = startup error), cookie-bearing CSRF check for non-`/api/auth` routes is already via `current_context` (no other route uses it yet — 9b wires it), `frontend_proxy.py` must forward the real client address; (2) `start.py` `--online`/`--localdev` setting `MTG_RUN_MODE`, `--online` refuses without TLS, `--localdev` refuses non-loopback; default-localuser auto-session (loopback + localdev only); (3) frontend login/signup slice with strength meter (`GET /api/auth/policy`), `api.js` sends `X-CSRF-Token` + credentials; (4) docs flip only at 9e; close 9a (Done_Backend/Done_Frontend, backlog) when all of this is done.
- **Decisions:** legacy start (no mode flag) is unchanged until 9e flips it; `psutil` is not installed, so LAN auto-detection is loopback-only until it is added as a dependency (decide at 9e; `MTG_ALLOWED_NETWORKS`/`--allow-network` works without it); frontend_proxy is backend→frontend so it does not hide client addresses. <choices made and why, so they aren't re-litigated>
- **Baselines / artefacts:** <snapshot paths, measured numbers, PARSER_VERSION>
- **Known failures (corrected; final full-cache recheck pending):** <red tests and whether they are ours or pre-existing>
- **Residue:** <what is still open once a run ends part-done — clusters, blockers, cards>
```


## PLR-9a · Run modes, account storage and authentication

- **Started / last update:** 2026-11-03 / 2026-11-03
- **Goal of this run:** build PLR-9a bottom-up on `feature/PLR-9`; nothing reaches `main` before the PLR-9e cutover (plan §2, no feature flag).
- **Done (built + tested):** config constants (`config.py`, "Accounts (PLR-9a)"); `services/password_policy.py` (red/yellow/green, blocklist `data/common_passwords.txt` is a tiny placeholder); `services/password_hasher.py` (scrypt, rehash-aware); `services/account_store.py` (`accounts.db`, versioned migrations, accounts/sessions/invitations/tombstones, atomic invite redemption); `tests/services/test_account_store.py` (27 green); `services/rate_limiter.py` (sliding-window failure limiter); `api/auth.py` (`/api/auth`: policy, me, signup-by-invitation, login with generic failures + dummy_verify + per-source/per-name throttle, logout, logout-all, password-change, player invitations create/list/revoke; `current_context`/`current_account` dependency enforcing `X-CSRF-Token` on cookie-bearing unsafe requests; cookie `mtg_session` HttpOnly/Lax, `__Host-` + Secure when `RUN_MODE=online`); `config.RUN_MODE` + throttle constants; `tests/api/test_api_auth.py` (16 green); `tests/api` 319 green; `services/network_gate.py` + request_guard peer gate (active only when `MTG_RUN_MODE` is set explicitly, i.e. by `start.py --lan/--online/--localdev`; fail-closed to loopback without psutil), `tests/services/test_network_gate.py`; `start.py` flags `--lan --online --localdev --allow-network --tls-cert/--tls-key/--behind-tls-proxy` (`resolve_run_mode`; no flag = legacy behaviour until 9e); default-localuser auto-session in `api/auth.py` (localdev + `is_local_request` + opt-out cookie on logout), `AccountStore.ensure_default_local`.
- **In progress:** —
- **Next step:** (1) `api/auth.py` + `get_account_store` in `api/dependencies.py`: signup (invite), login (generic failure, `dummy_verify` for unknown accounts, throttle), me, logout, logout-all, password-change, invitations create/list/revoke; session cookie (LAN profile: distinct name, HttpOnly, SameSite=Lax) + CSRF token header; (2) request_guard: peer-address allowlist (`MTG_ALLOWED_NETWORKS`, fail-closed), CSRF for cookie-bearing requests, `frontend_proxy.py` real client address; (3) `start.py` `--online`/`--localdev`, config mode; default-localuser; admin seed `admin`/`admin` is PLR-9d; (4) frontend login/signup slice with strength meter, `api.js` CSRF; (5) docs flip only at 9e.
- **Decisions:** legacy start (no mode flag) is unchanged until 9e flips it; `psutil` is not installed, so LAN auto-detection is loopback-only until it is added as a dependency (decide at 9e; `MTG_ALLOWED_NETWORKS`/`--allow-network` works without it); frontend_proxy is backend→frontend so it does not hide client addresses. scrypt (stdlib) is the default hasher since `argon2-cffi` is not installed; `PasswordHasher` interface allows Argon2id later. Admin and player accounts share `accounts` with a `role` column; player login must reject admins.
- **Baselines / artefacts:** `venv/bin/python -m pytest tests/services/test_account_store.py -q`.
- **Known failures (corrected; final full-cache recheck pending):** none; full backend suite green (18447 passed) after the storage layer.
- **Residue:** everything under *Next step*; blocklist source/size; Argon2id decision with measurements.
