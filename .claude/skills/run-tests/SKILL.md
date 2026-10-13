---
name: run-tests
description: Run the backend test suite at the right size. Picks tests by the domain of the git diff (card, engine, parser, session_bots, multiplayer, api, db, external, analysis, config_ops, models, frontend), widens only when the change demands it, and runs in parallel. Use whenever you need to run, verify or "make sure the tests are green" after a change; use instead of a bare `pytest` run, which costs several minutes.
---

# run-tests

The suite is ~13k tests; a serial full run takes ~5 minutes (it took over an hour before the shared test-card-cache connection, see Rules), `-n 4` ~2.5 minutes. Almost every change needs a small slice. Tests carry a `domain_<x>` marker (assigned from `backend/tests/domains.py`), and `backend/scripts/select_tests.py` turns the git diff into the smallest sensible slice.

Rule of thumb: **tier 1 is the domain you changed.** A new card does not need websocket, lobby, API or database tests.

## Default flow

From the repo root:

```bash
python backend/scripts/select_tests.py            # show the plan (JSON): tier, domains, why
python backend/scripts/select_tests.py --run      # run it (adds -n 4 for larger slices)
```

(Use the backend venv's python: `backend/venv_win/Scripts/python.exe` on Windows, `backend/venv/bin/python` elsewhere. `run_tests.py` resolves the venv itself for the pytest child.)

Then decide:

1. **Red** -> fix it, rerun only the failures: `python backend/scripts/run_tests.py --lf <same args>`; do not widen the tier to hunt a failure.
2. **Green at T1** -> usually done. Widen (`--tier 2`) when you changed shared engine behaviour or an interface other domains consume; `DEPENDENTS` in `domains.py` lists who consumes whom.
3. **Before closing an engine/parser ticket** -> `--tier 4` (adds `--full-cache`; CLAUDE.md requires it). Never point `MTG_CACHE_DIR` at the production cache.

## Tiers

| Tier | Runs | Typical trigger |
| --- | --- | --- |
| T1 | tests of the changed domain, narrowed to the changed module / card | new card, handler tweak, one engine module |
| T2 | T1 plus consumer domains | engine/parser interface change |
| T3 | whole backend, no full-cache | wide-reach files (`continuous.py`, `binding/core.py`, `gate.py`, `conftest.py`, model core), unclassified files, empty diff |
| T4 | everything incl. `--full-cache` | closing a ticket |

Doc/markdown-only diffs run nothing. Frontend changes: run the `frontend` checks instead (`cd frontend && npm run lint`, `node scripts/i18n-verify.mjs`, `frontend/tests`) and verify in a real browser; the plan prints `frontend_checks: true`.

## Direct control

```bash
pytest -m domain_card -n 4                  # a whole domain (from backend/, in the venv)
pytest -m "domain_multiplayer or domain_api"
pytest tests/test_x.py -n 0                 # no parallelism: use for debugging one test
python backend/scripts/test_profile.py --run -n 4   # where does the time go
```

## Rules

- Never run two `-n` pytest sessions at the same time: workers use `backend/cache/test_gw<N>/` and would collide.
- The suite shares one `CardDatabase(DB_PATH)` connection per process (`tests/conftest.py`); a test that needs a private card DB uses `:memory:` or `tmp_path`. `MTG_TEST_NO_DB_SHARE=1` turns the sharing off.
- Parallel runs (`-n`) give every xdist worker its own copy of the card cache (`backend/conftest.py`); never share one SQLite file between workers.
- A slice is only as good as the mapping: if a test file lands in the wrong domain, fix `backend/tests/domains.py` (tables, not code) rather than working around it.
- Report honestly: which tier ran, what was deliberately not run, failures with their output. Do not call a T1 run "the suite is green".
- New domain-crossing tests (a card test that also boots a session/websocket) belong in the owning domain's tests instead; keep a card's test at engine level unless the session path is what is being tested.
