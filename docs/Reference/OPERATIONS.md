# Operations: running, testing, configuration

Load when touching startup, networking, config, workers, logging, the card cache
or the test setup.

## Processes and network

- `setup/start.py` runs two processes: backend `uvicorn` and the frontend static
  server `no_cache_server.py` (loopback-only, always). The backend reverse-proxies
  everything outside `/api`/`/ws` to it (`api/frontend_proxy.py`,
  `config.FRONTEND_ORIGIN`), so **a browser only needs the backend port**.
  `_LOCAL_DEV_ORIGIN_REGEX` (`api/app.py`) therefore admits only
  `localhost`/`127.0.0.1`; the two-origin case is `--frontend-only`.
- **Run modes** (`start.py`, `config.RUN_MODE`, exported as `MTG_RUN_MODE`; operator guide
  [SERVER_GUIDE.md](SERVER_GUIDE.md), design [the plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md)). With no
  flag the app starts in **LAN** mode: it binds all interfaces, serves only clients inside the peer
  allowlist (`services/network_gate.py`, `MTG_ALLOWED_NETWORKS` / `--allow-network`; default the
  host's interface subnets plus loopback), and **requires accounts** (invitation signup, server-side
  sessions, CSRF). `--online` is HTTPS only (own TLS or `--behind-tls-proxy`; the latter binds loopback, honours `X-Forwarded-*` only from `--trusted-proxy` / `MTG_TRUSTED_PROXIES` peers, and treats nothing on the proxied port as "local"; local admin there uses the loopback-only `--admin-port`
  listener, default backend port + 1, same process, serving only `/admin` and `/api/admin`), `__Host-` cookies, no
  allowlist, remote `/admin` only with password + TOTP (a genuinely local admin request needs no TOTP in any mode); `--localdev` is loopback only and signs the
  built-in `local` player in automatically. `--host` only overrides the bind address; it never turns
  accounts off. The allowlist is a convenience boundary, not authentication. `/admin` and
  `/api/admin` are loopback-only (plus HTTPS+MFA in `--online`), with per-request credentials and no
  admin cookie; the card-pool/combo update routes and MCP token rotation need admin credentials.
  `settings.js` `DEFAULT_SERVER_URL` is `window.location.origin` so LAN browsers
  call the same host.
- **Request guard** (`api/request_guard.py`, one pure-ASGI middleware, one
  allowlist; BUG-40/41/42). Host: only `localhost`/`127.0.0.1`/`::1`, the
  `--host` address (`start.py` exports it as `MTG_BIND_HOST`, `config.BIND_HOST`)
  and `MTG_ALLOWED_HOSTS` (tests set `testserver` in `backend/conftest.py`);
  anything else gets 400 (DNS rebinding). With a wildcard bind (`--host 0.0.0.0`)
  any IP-literal Host is accepted, since an IP cannot be rebound; names stay
  restricted. WebSocket handshakes with a foreign `Origin` close with 1008
  (CSWSH). Unsafe methods (anything but GET/HEAD/OPTIONS/TRACE) with a foreign
  or `null` `Origin` get 403; with no `Origin`, a `Sec-Fetch-Site` other than
  `same-origin`/`none` gets 403. Requests with neither header (MCP stdio client,
  scripts, `TestClient`) pass: they are not a CSRF vector, and a missing-Origin
  hard reject would break them. Allowed origins: `localhost`/`127.0.0.1` on any
  port (the `--frontend-only` two-origin case), or an origin equal to the
  validated Host (same origin) / an exact allowed host name (never the
  wildcard IP-literal rule, which is Host-only).
- Backend startup allows up to 300 seconds for the card catalogue to load on a
  cold or slow disk. After 15 seconds it reports that startup is still in
  progress; if the process exits, the launcher fails immediately with its exit
  code and the backend's error output.
- **Starting must stay offline-safe.** `ensure_backend_venv()` installs with
  `pip --no-index` first and only falls back to an index run; a fresh venv can be
  built from `setup/wheels/` (`setup/install.py --download-wheels`). Nothing else
  at start touches the network (no external frontend assets; card data from
  `backend/cache/`; tokens/dungeons/variants are committed JSON in
  `mtg_analyzer/data/`). Do not add an unconditional `pip install --upgrade pip`.
  Pinned by `backend/tests/test_setup_offline_start.py`.

## Data protection (accounts.db, logs, files)

- **`accounts.db` is SQLCipher-encrypted** (`services/account_crypto.py`, binding `sqlcipher3-wheels`
  in `requirements.txt`, so it comes with `install.py` and `--download-wheels`). It holds password
  hashes, session/invitation digests, the audit log and the admin TOTP secrets; WAL, journal and temp
  data are encrypted with it. The other stores (`decks.db`, `player_assets.db`, caches) are plain
  SQLite and rely on an encrypted volume; no store is described as encrypted unless it is.
- **Key**: 64 hex characters from `MTG_ACCOUNTS_DB_KEY`, else the key file
  (`MTG_ACCOUNTS_DB_KEY_FILE`, default `~/.decklab/accounts.key`, mode 600, refused if group/other
  readable or inside `MTG_DATA_DIR`). Never in `config.json`. A missing/wrong key or a legacy
  plaintext file makes the backend **refuse to start** (`_require_account_store` in the lifespan);
  there is no plaintext fallback and no fresh database is created over an existing one. Only a
  brand-new install (no key, no database) generates a key file, with a warning to back it up. No OS
  keychain: it would add a platform-specific dependency and does not exist on headless servers.
- **Operator commands** (`scripts/manage_accounts.py`): `init-key`, `encrypt-db` (convert a legacy
  plaintext file: export, verify, atomic swap), `rekey`, `backup`/`restore` (encrypted copies, pruned
  to `MTG_ACCOUNTS_BACKUP_KEEP`), `status`. Procedures in SERVER_GUIDE section 4c and 7.
- **Files**: the production store factories call `account_crypto.harden_data_dir`, which sets the
  data directory to 0700 and databases, WAL/journal files, logs, backups and the MCP token to 0600
  (POSIX; Windows relies on the profile directory's ACL). `backend/data` is git-ignored, never
  served (the frontend proxy only fetches from the loopback frontend server's own root), and bug
  reports/exports never include it.
- **Security-event log** (`services/security_log.py`, `api/security_events.py`): logger
  `decklab.security`, separate from the application log, rotating file
  `MTG_DATA_DIR/logs/security.log` (`MTG_SECURITY_LOG_FILE`, empty disables the file;
  `MTG_SECURITY_LOG_MAX_BYTES` 5 MiB x `MTG_SECURITY_LOG_BACKUPS` 9 rotated files). One `key="value"`
  line per event: login/signup/recovery outcomes, session lifecycle, password changes, 401/403/429
  refusals of `/api/` calls, every `/api/admin` request (with the admin's uuid), and a mirror of every
  `audit_log` entry. Values are control-character-stripped and cut to 120 characters; ids in paths
  collapse to `{id}`; field names that suggest a secret raise in the formatter and in tests.
  Cookies, passwords, tokens, CSRF, TOTP and request bodies are never logged. WebSocket refusals are
  not logged by the middleware (the lobby socket reports its own close reasons).
- **Retention** (`AccountStore.purge_expired`, hourly with the deletion sweep, constants in
  `config.py`): ended sessions 7 days, finished recovery credentials 7 days, finished invitations 30
  days, lapsed name tombstones at once, audit log 365 days (`MTG_SESSION_RETENTION_DAYS`,
  `MTG_RECOVERY_RETENTION_DAYS`, `MTG_INVITATION_RETENTION_DAYS`, `MTG_AUDIT_RETENTION_DAYS`).
- **Browser output**: `security_headers.py` adds `Cache-Control: no-store` (unless a route set its own)
  to `/api/auth`, `/api/admin`, `/api/me`, `/api/mcp-*`, `/api/decks`, `/api/game`, `/api/solo`,
  `/api/multiplayer`, `/api/bug-reports`, `/api/import`, `/api/analysis` and `/admin`. Card data and
  card images stay cacheable. There is no service worker and no Cache Storage use in the frontend.
- Requirement-to-test map: [ACCOUNT_SECURITY_TEST_MAP.md](ACCOUNT_SECURITY_TEST_MAP.md).

## Tests

- **Agent interpretation:** `SKIPPED` is expected for disabled `full_cache` and
  `real_socket` tiers and for documented scenario-dependent guards. Explicitly
  marked `XFAIL` results are expected failures; an arbitrary `FAILED`/`ERROR`
  is not. Retain the guards and report the executed tier plus skipped coverage.
  If `--socket-tests` was requested in a restricted sandbox, a denied local
  bind (`EPERM`/`EACCES`, e.g. `Operation not permitted`) on a `real_socket`
  test is an environment limitation. Report that integration check as blocked;
  do not change production socket/security behavior to make it pass, and do
  not describe it as verified. Assertion failures, unexpected passes, connection
  timeouts/refusals and unmarked test failures still need investigation.
- `cd backend && python -m pytest -q`, or `python backend/scripts/run_tests.py
  [pytest args]` (finds the venv itself; adds `--hard-timeout SECONDS`, default
  1800s, killing the process group for hangs the per-test timer cannot reach).
- `pytest-timeout` aborts any test over 20s (`backend/pytest.ini`).
- Tests marked `real_socket` are excluded from the standard run: they bind OS
  loopback sockets, which restricted sandboxes refuse. Run that integration tier
  explicitly with `pytest --socket-tests -m real_socket` on a host that permits
  local listeners, or add `--socket-tests` to the whole suite. This opt-in is
  independent of `--full-cache`; in-process HTTP/WebSocket tests still run by
  default. The marked cases cover the live admin listener, admin-page upstream,
  frontend proxy and MCP stdio/HTTP integration.
- For runtime comparisons, use `python backend/scripts/run_tests.py --timings
  /tmp/tests-regular.xml -q` from the repository root, and a separate
  `/tmp/tests-full-cache.xml` with `--full-cache` for the full tier (choose an
  external scratch path on Windows). This writes JUnit per-test totals and
  prints the slowest 25 setup/call/teardown phases. Compare the same test IDs,
  cache population and tier; do not compare profiled and unprofiled wall times.
  Measure startup/collection separately with `time python -m pytest
  --collect-only -q` in `backend/`; JUnit test times do not include collection.
- Catalogue tests use `tests.support.card_cache.get_cached_card` for named
  lookups on one session-owned connection, closed by their session fixture.
  Each lookup deserializes a fresh `Card`; database-writing tests retain their
  own isolated stores. Forward-only bot fixtures pass `keep_history=False`;
  undo/history tests opt in explicitly. Application sessions retain history
  by default, including those with no takeback budget.
- Account-key/backup isolation uses one session temp root and fresh private
  subdirectories per test. Avoid per-test numbered `tmp_path_factory.mktemp`
  calls for global fixtures: pytest scans the growing parent directory for
  each allocation, making that setup cost quadratic in the test count.
- **Plain `pytest -q` skips the full-cache tier** (`test_cube_batch_*`, anything
  marked `full_cache`): run `pytest --full-cache` or `MTG_FULL_CACHE_TESTS=1`
  before closing engine or parser work. It reads an isolated cache:
  `backend/conftest.py` redirects `MTG_CACHE_DIR` to `backend/cache/test/`.
  **Never point `MTG_CACHE_DIR` at the production cache** to run tests; that
  `setdefault` is the only protection for the 35k-card `backend/cache/db/cards.db`.
- Non-trivial frontend changes: verify in a real browser (Playwright in
  `backend/venv`, Chromium against the running servers), not only by API replay.
  No JS build step, no JS test runner.

## Configuration (`mtg_analyzer/config.py`)

- Precedence per value: **`MTG_*` env var > `mtg_analyzer/config.json` > default**.
  The JSON is committed with every knob at its default plus per-section
  `_comment`s (keys starting `_` are ignored; a missing/malformed file is ignored).
  `MTG_CONFIG_FILE` points elsewhere. Service modules keep their old constant
  names (`CACHE_ROOT`, `DEFAULT_DB_PATH`, …) as aliases onto `config.py`.
- **One uvicorn process on purpose** (session manager, lobby and analysis jobs are
  in-memory singletons). Knobs: `SERVER_THREAD_WORKERS` (`--server-threads`, 40;
  AnyIO request-thread pool, ceiling on games mid-step),
  `DYNAMIC_ANALYSIS_WORKERS` (`--analysis-jobs`, 4; concurrent jobs),
  `DYNAMIC_ANALYSIS_MATCH_WORKERS` (`--analysis-match-workers`, 0 = one per core,
  1 = off; process pool per job, in-process below `_MIN_MATCHES_FOR_PROCESS_POOL`).
- Analysis queue (ANA-6, `services/job_runner.py`): a start joins a bounded queue and is
  dispatched round-robin per owner (account or `anon:` id) into the `DYNAMIC_ANALYSIS_WORKERS`
  slots. Knobs (env / `limits` section): `MTG_DYNAMIC_ANALYSIS_QUEUE_MAX` (50 waiting jobs;
  full = 503 `analysis_queue_full`), `MTG_DYNAMIC_ANALYSIS_QUEUE_MAX_PER_OWNER` (3 queued+running
  per owner; 429 `analysis_owner_limit`), both with `Retry-After`, never an eviction.
  `MTG_DYNAMIC_ANALYSIS_RESULTS_PER_OWNER` (5) and `MTG_DYNAMIC_ANALYSIS_RESULT_TTL` (21600 s)
  bound the finished results kept per owner; only an owner's own new results roll theirs off.
  Poll: `queued` (with `queuePosition`) / `running` / `done` / `failed` / `cancelled`;
  `DELETE /api/analysis/dynamic/{id}` cancels (owner only). Shutdown (app lifespan) drops queued
  jobs and cancels running ones.
- Logging: `config.LOG_LEVEL` (`MTG_LOG_LEVEL`, `logging.level`,
  `./start.sh --log <level>`) sets the `mtg_analyzer` logger, default WARNING (the
  engine/parser are chatty at INFO); root stays WARNING.
- Scryfall policy: `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY`,
  `./start.sh --scryfall-primary`), default `False` = **cache-primary**: a cached
  card is served even if `stale` (`lazy_card_loader._is_fresh`), never silently
  refetched. `True` refetches stale rows. A never-cached name is always fetched once.
- Resource limits (BUG-43, `config.py` "Resource limits"; env `MTG_SESSION_TTL`,
  `MTG_SESSION_MAX`, `MTG_ANON_SESSION_MAX_PER_OWNER`, `MTG_ANON_SESSION_MAX_TOTAL`, `MTG_LOBBY_MAX_PLAYERS`, `MTG_LOBBY_MAX_GAMES`,
  `MTG_UPLOAD_MAX_BYTES`, `MTG_PLAYER_ASSET_MAX_COUNT`, `MTG_PLAYER_ASSET_MAX_BYTES`, `MTG_PLAYER_ASSET_STORE_MAX_BYTES` (whole store, 1 GB),
  `MTG_BUG_REPORT_MAX_COUNT`, `MTG_BUG_REPORT_MAX_BYTES`; config.json section
  `limits`). Idle non-table game sessions are swept (TTL from last access) and the
  least recently used one is evicted past the cap; a session a lobby table points
  at is never evicted. Uploads are refused with 413 by Content-Length before the form is parsed, and again by a chunked read. **Bug reports
  are never rotated or deleted**: past the cap a new report is refused (507) until
  you clear old ones by hand.
- Alternate printing names: `CardDatabase.get_card` matches canonical names, front
  faces, `flavor_name` and verified `card_aliases`; aliases point to a canonical
  name and survive payload schema resets and offline reseeding, but not deleting
  the whole cache. An unknown printing name costs one Scryfall lookup. Scripts must
  pass `DEFAULT_DB_PATH` explicitly (`CardDatabase()` alone is in-memory).

## Server messages (de/en)

User-facing refusals (HTTP error details, lobby/WebSocket reasons, analysis-queue refusals) carry a stable `code` plus a `message` in the caller's language. The catalogue is `backend/mtg_analyzer/i18n/catalogue.py` (one `de` and one `en` dict keyed by code, `{placeholder}` formatting); `message(code, lang, **params)` renders it and never raises (other language, then the code). The language is the `mtg_lang` cookie, then `Accept-Language` (q-values), then `de`.

- HTTP: `raise api_error(status, "code", **params)` (`mtg_analyzer.i18n`); `api/errors.py` adds the localized `message` for every `HTTPException` whose `detail` is `{"code": ...}`, so the body is always `{"detail": {"code", "message", ...params}}`. Plain-string details in `api/` are forbidden (`tests/api/test_api_server_messages.py`).
- Services without a request raise `LocalizedError(code, **params)` (`LobbyError`, `AssetQuotaError`, `ArchidektFetchError` derive from it); the API boundary calls `error_from(exc, status)`. Any other exception (engine / rules refusals from `game/`, `game_session`) passes its own English text through as code `action_rejected`.
- WebSocket: the final `disconnected` frame keeps `reason` and adds `message` (`ws_<reason>`); `error` frames carry `code` and `message`.
- To add a message: add the code to both dicts in `catalogue.py` (the parity test fails otherwise), raise it, and, if the frontend has its own wording, map the code in `frontend/src/js/serverError.js` or add `errors.<code>` to the locale catalogs. Codes are never renamed. The frontend shows its own locale text when one exists, else the server `message`, else the code. Internal / log-only text stays English and out of the catalogue.

## Launcher console

The launcher prints the command menu on every start/restart. Routine HTTP access
logs are disabled for both servers; frontend errors and backend application logs
remain visible.

`start.sh` / `start.bat` (`setup/start.py`) accept commands followed by Enter:
`c` stops the started servers, `r` restarts them with the same options,
`i` lists currently connected lobby players and multiplayer tables (name, ID,
status) plus other game WebSocket connections, and `t` lists the currently live
Python threads in the backend process (not the configured worker limit or child
processes). Restarting clears in-memory games and connections. Commands also work
in backend-only mode; frontend-only mode supports stop/restart but has no backend
status. EOF/detached stdin leaves process supervision running. A child process
exiting stops its sibling as well.

Status is read from `/api/console-status` using a random per-launch secret passed
to the backend through `MTG_CONSOLE_TOKEN`; without that secret the endpoint
returns 404. Direct uvicorn launches do not enable launcher diagnostics.
