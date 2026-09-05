# MTG Deck Analyzer

A Magic: The Gathering deck analyzer and rules-driven game engine.

## Project Structure

```
backend/    Python backend (FastAPI app, rules engine, effects, services)
frontend/   Browser client (no build step: static HTML/CSS/JS)
setup/      Cross-platform install/start scripts (install.py, start.py)
docs/       Architecture, requirements, and implementation specs (developer-facing)
user-docs/  How to use the app — deck import, Goldfisch, Replay/Puzzle, settings (EN + DE)
```

See [docs/README.md](docs/README.md) for the full documentation map,
[docs/concepts/03_ARCHITECTURE_AND_BUILDPLAN.md](docs/concepts/03_ARCHITECTURE_AND_BUILDPLAN.md)
for the overall architecture, and
[docs/implementation-state/10_COMPLETION_ROADMAP.md](docs/implementation-state/10_COMPLETION_ROADMAP.md)
for what's built vs. still open. Just want to *use* the app? See
[user-docs/](user-docs/) instead.

## Install & Run

Cross-platform (macOS/Linux/Windows), pure Python standard library — no
extra tooling to install first, just a Python 3 interpreter on PATH.

```bash
# macOS/Linux
./install.sh
./start.sh
```

```bat
:: Windows
install.bat
start.bat
```

(`setup/install.py` / `setup/start.py` also work directly via
`python3 setup/install.py` / `python setup/start.py` — the `.sh`/`.bat`
files at the repo root are thin OS-native wrappers around them.
Running `./install.sh` first is optional: `start.sh` ensures the venv
itself, so a fresh checkout works with just `./start.sh`.)

Useful variants:

```bash
./start.sh --backend-tests       # run backend pytest before starting
./start.sh --backend-only        # start only the FastAPI backend
./start.sh --frontend-only       # start only the static frontend server
./start.sh --no-browser          # skip opening a browser tab automatically
./start.sh --log info            # backend log level (default: warning)
./start.sh --analysis-match-workers 8   # parallelise dynamic analysis over 8 processes
```

### Development and test tooling

The normal installer deliberately installs only what is needed to run the
application. For frontend linting and other development-only tooling, run this
separate setup once:

```bash
./setup_dev.sh             # macOS/Linux
setup_dev.bat              # Windows
```

It creates a project-local Node runtime in `frontend/.nodeenv` and installs
ESLint into `frontend/node_modules`; neither is used by `start.sh` and both are
ignored by Git. Run the frontend check with:

```bash
(cd frontend && PATH="$PWD/.nodeenv/bin:$PATH" .nodeenv/bin/npm run lint)
```

Runtime settings (paths, Scryfall, multiplayer timers, worker pool sizes,
log level) live in `backend/mtg_analyzer/config.json` — edit it, or
override any value with the matching `MTG_*` environment variable or the
`start.sh` flag (flag > env var > file > built-in default).

`setup/install.py` creates `backend/venv` and installs `backend/requirements.txt`
into it — this is the whole backend, encapsulated in its own virtual
environment (never installed into the system Python). `start.py` does
the same venv setup on every run (cheap/idempotent if already up to
date), starts the backend FastAPI app (`mtg_analyzer.api.app:app`, via
uvicorn) plus the frontend static server at `http://localhost:8765`
(Ctrl+C to stop both); add `--backend-tests` to also run the backend's
pytest suite first, `--port` to change the frontend port,
`--backend-only`/`--frontend-only` to start just one side, `--no-browser`
to skip auto-opening a tab. See [docs/implementation-state/BACKLOG.md](docs/implementation-state/BACKLOG.md)
for what's still open.

### Starting without an internet connection

Once installed, the app starts **fully offline** — nothing in a normal
start reaches the network:

* `start.py`'s venv check runs pip with `--no-index`, so an
  already-installed backend is verified purely locally (a fraction of a
  second, no socket opened). Only a genuinely missing or outdated
  dependency triggers a second, index-using attempt.
* The frontend loads no external script, stylesheet, font or image — the
  static server serves everything, and all card art comes from the
  backend's own on-disk cache (`backend/cache/`, see
  [docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md](docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md)).
* Tokens, dungeons and the casual-variant cards (planes/schemes/
  Vanguard avatars) are committed JSON catalogues in
  `backend/mtg_analyzer/data/`, not lookups.

The one thing that *does* need the internet is the very first
dependency install (and looking up a card that has never been cached).
To prepare a machine that will be offline, cache the dependency wheels
while you still have a connection:

```bash
python3 setup/install.py --download-wheels   # fills setup/wheels/
```

Every later install — including creating a brand-new `backend/venv` —
then resolves from that wheelhouse without a connection. Wheels are
specific to the OS/architecture/Python version they were downloaded for,
so run this on the machine (or an identical one) that will use them.

To work on the backend directly:

```bash
source backend/venv/bin/activate   # backend/venv/Scripts/activate.bat on Windows
pytest backend/tests/
```

See [frontend/README.md](frontend/README.md) for frontend details.

## License

GPL-2.0, see [LICENSE](LICENSE).
