# DeckLab

A Magic: The Gathering deck analyzer with a rules-accurate game engine. Import
a deck, analyze it, then actually play it — every move is validated server-side
against the Comprehensive Rules.

## What it does

* **Deck import & analysis** — paste a list or import from Archidekt, keep
  decks in a saved-decks library (format legality, colour identity, cube
  pools, favorites), and get a static analysis plus Commander Spellbook combo
  matching and an unofficial Bracket estimate.
* **Goldfisch** — play a saved deck alone against the real rules engine: step
  through the turn, play lands, tap mana, cast spells with the stack, attack.
* **Solo gegen Bots** — a real multiplayer game (turns, priority, hidden
  hands) against 1–3 bots, no lobby needed. Bot policies range from simple to
  a deck-aware Smart Bot and an optional LLM-driven bot.
* **Multiplayer** — two to four players at one table (lobby, seats, shared
  board, reconnects, spell timers, take-backs, emotes), with bots able to fill
  seats.
* **Replay / Puzzle** — build an arbitrary board, play from there, and
  export/import the position as JSON.
* **Engine-Status, card cache, Einstellungen, Profil** — engine coverage
  documentation, the local card cache, server/LLM settings, and per-player
  preferences (name, token art, card sleeves).

The interface is available in English (default) and German, switchable in
Einstellungen / Settings; MTG keyword names stay English. Oracle text is turned into behaviour by a fail-closed parser
plus hand-authored card entries — see the Engine-Status tab and
[docs/implementation-state/](docs/implementation-state/) for exactly what is
covered.

## Project Structure

```
backend/    Python backend (FastAPI app, rules engine, effects, services)
frontend/   Browser client (no build step: static HTML/CSS/JS)
setup/      Cross-platform install/start scripts (install.py, start.py)
docs/       Architecture, requirements, and implementation specs (developer-facing)
user-docs/  How to use the app — deck import, analysis, Goldfisch, Replay/Puzzle,
            multiplayer, settings, sources & licenses (EN + DE)
```

[CLAUDE.md](CLAUDE.md) (also read as [AGENTS.md](AGENTS.md)) is the
developer-facing project wiki: architecture, conventions and where to look first.

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
./start.sh --port 9000 --backend-port 9001   # change the frontend / backend ports
./start.sh --log info            # backend log level (default: warning)
./start.sh --server-threads 60   # concurrent blocking requests (games mid-step)
./start.sh --analysis-jobs 2     # concurrent dynamic-analysis jobs
./start.sh --analysis-match-workers 8   # parallelise dynamic analysis over 8 processes
./start.sh --scryfall-primary    # always refetch stale cached cards from Scryfall
./start.sh --host 0.0.0.0        # make the app reachable from other computers
```

> **`--host` and security:** the app has **no authentication**. Anyone who can
> reach the host/port can read and write saved decks and uploads and join any
> game, so the default stays loopback-only. Only use `--host` on a network you
> trust.

The browser needs to reach only the backend's port: the backend
reverse-proxies the static frontend, so the frontend server itself stays
loopback-only.

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
log level, bug-report directory) live in `backend/mtg_analyzer/config.json` — edit it, or
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

The card pool itself (~35k Oracle cards) is seeded from Scryfall's bulk data
and refreshed with `backend/scripts/update_card_pool.py`; see
[docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md](docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md).
Commander Spellbook combo data is downloaded only on first combo matching or
an explicit refresh.

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
cd backend && python -m pytest -q
```

or, from any shell without activating the venv:
`python backend/scripts/run_tests.py [pytest args...]`. A plain run skips the
tests that need the full card cache; add `--full-cache` (or set
`MTG_FULL_CACHE_TESTS=1`) to include them — they use an isolated cache, never
the production one.

Local bug reports (the bug icon beside Settings) are saved as compressed JSON
in the Git-ignored `bug-reports/` directory; see [CLAUDE.md](CLAUDE.md) for the
format and how to inspect them.

See [frontend/README.md](frontend/README.md) for frontend details.

## License

GPL-2.0, see [LICENSE](LICENSE). Card data, images and rules text come from
third parties; see
[user-docs/en/10_sources_and_licenses.md](user-docs/en/10_sources_and_licenses.md).
