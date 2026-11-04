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
- **LAN access is opt-in** via `start.py --host HOST` (uvicorn `--host`). The app
  has **no authentication**: anyone who can reach the port can read/write decks
  and uploads and join any game. Never make it the default. *(Planned change, PLR-9a: the default becomes a LAN mode
  restricted to the host's own IP ranges, with accounts; `--online` and `--localdev` select the secure and login-free
  modes — see [the plan](../concepts/15_ACCOUNT_SYSTEM_PLAN.md). This text stays authoritative until then.)*
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

## Tests

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
- Logging: `config.LOG_LEVEL` (`MTG_LOG_LEVEL`, `logging.level`,
  `./start.sh --log <level>`) sets the `mtg_analyzer` logger, default WARNING (the
  engine/parser are chatty at INFO); root stays WARNING.
- Scryfall policy: `SCRYFALL_PRIMARY` (`MTG_SCRYFALL_PRIMARY`,
  `./start.sh --scryfall-primary`), default `False` = **cache-primary**: a cached
  card is served even if `stale` (`lazy_card_loader._is_fresh`), never silently
  refetched. `True` refetches stale rows. A never-cached name is always fetched once.
- Resource limits (BUG-43, `config.py` "Resource limits"; env `MTG_SESSION_TTL`,
  `MTG_SESSION_MAX`, `MTG_LOBBY_MAX_PLAYERS`, `MTG_LOBBY_MAX_GAMES`,
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
