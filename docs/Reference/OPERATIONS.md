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
  and uploads and join any game. Never make it the default.
  `settings.js` `DEFAULT_SERVER_URL` is `window.location.origin` so LAN browsers
  call the same host.
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
  1800s (the full-cache suite takes ~7 min), killing the process group for hangs the per-test timer cannot reach).
- `pytest-timeout` aborts any test over 20s (`backend/pytest.ini`).
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
