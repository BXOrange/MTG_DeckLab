"""Central configuration: on-disk paths and small runtime constants.

Reference: docs/implementation-state/Done_Backend.md "Configuration".

Before this module existed, `CACHE_ROOT`/`DEFAULT_DB_PATH`
(`card_database.py`), `DATA_ROOT`/`DEFAULT_DECKS_DB_PATH`
(`deck_database.py`), `DEFAULT_PLAYER_ASSETS_DB_PATH`
(`player_assets.py`) and the Scryfall/`ImageCache` User-Agent constants
were each a hard-coded module constant with no override hook — a one-off
script or test run pointed at the same repo-relative cache/data
directories as any dev server that happened to be running, and (now that
`schema_version.py` can wipe a stale cache on open) could stomp its
database out from under it. Every on-disk path and related constant now
lives here instead.

Each value is resolved with a fixed precedence:

    environment variable  >  config file  >  built-in default

so a test or one-off script keeps its per-process `MTG_*` override, while
a deployment can set persistent values in a committed file without
touching code or exporting a dozen env vars. The config file is JSON,
`backend/mtg_analyzer/config.json` by default (overridable with
`MTG_CONFIG_FILE`); a missing or unreadable file is simply ignored and
every value falls back to its default. Sections/keys mirror the env var
names — see `config.json` itself, which ships with every knob written out
at its default plus a per-section ``_comment`` (keys starting with ``_``
are ignored by the loader).

Env vars (all optional; defaults reproduce the pre-config-module paths):
  MTG_CONFIG_FILE — path to the JSON config file (default:
    backend/mtg_analyzer/config.json)
  MTG_CACHE_DIR   — root of the disposable Scryfall cache (DB + images)
  MTG_DATA_DIR    — root of persistent user data (saved decks, player assets)
  MTG_USER_AGENT  — User-Agent sent to Scryfall (API + image CDN)
  MTG_SCRYFALL_MIN_REQUEST_INTERVAL — seconds between Scryfall API requests
  MTG_SCRYFALL_PRIMARY — "1"/"true"/"yes" switches LazyCardLoader's loading
    policy from cache-primary (default) to scryfall-primary; see
    SCRYFALL_PRIMARY below. Also settable via `setup/start.py
    --scryfall-primary`.
  MTG_LOG_LEVEL — log level for the app's own `mtg_analyzer.*` loggers
    (CRITICAL/ERROR/WARNING/INFO/DEBUG); default WARNING. `setup/start.py`
    passes the same value to uvicorn as `--log-level`.
  MTG_MULTIPLAYER_IDLE_TIMEOUT — seconds a multiplayer player may hold
    priority without acting before the server drops their connection
  MTG_MULTIPLAYER_DISCONNECT_GRACE — seconds a disconnected player's seat
    is held open for them to reconnect into
  MTG_MULTIPLAYER_SPELL_TIMER — seconds the board's per-priority countdown
    runs before it auto-passes for the player holding priority (0 = off,
    manual passing only); overridable per table in the Multiplayer setup
  MTG_SERVER_THREAD_WORKERS — size of the server's blocking-request worker
    thread pool; how many games can be mid-step at once (see below)
  MTG_DYNAMIC_ANALYSIS_WORKERS — how many dynamic-analysis *jobs* run at once
  MTG_DYNAMIC_ANALYSIS_MATCH_WORKERS — how many worker *processes* one job
    fans its independent match simulations across (0 = one per CPU core)
"""

from __future__ import annotations

import json
import os
import warnings
from pathlib import Path
from typing import Any

#: backend/ directory (this file lives at backend/mtg_analyzer/config.py) —
#: cache/ and data/ have always lived here, not at the outer repo root.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    override = os.environ.get(name)
    return Path(override).expanduser().resolve() if override else default


# -- Config file -------------------------------------------------------
#
# Loaded once at import. `env var > file > default` is enforced by the
# `_cfg_*` resolvers below; this block only turns the file into a dict.

#: Default location of the committed JSON config file. Kept next to this
#: module (not at the repo root) so it travels with the package and a
#: `MTG_DATA_DIR`/`MTG_CACHE_DIR` relocation doesn't drag it along.
CONFIG_FILE = _env_path("MTG_CONFIG_FILE", Path(__file__).resolve().parent / "config.json")


def _load_config_file(path: Path) -> dict[str, Any]:
    """Parse the JSON config file into a nested dict.

    A missing file is normal (every value then falls back to its default);
    an unreadable/malformed one warns once and is otherwise treated as
    empty, so a typo in the file can never stop the server from starting.
    A non-object top level (a bare list/number) is likewise ignored.
    """
    try:
        with open(path, "rb") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        warnings.warn(f"Ignoring unreadable config file {path}: {exc}", RuntimeWarning, stacklevel=2)
        return {}
    return data if isinstance(data, dict) else {}


_FILE_CONFIG = _load_config_file(CONFIG_FILE)


def _file_value(section: str, key: str) -> Any:
    """The `[section] key` value from the config file, or None if absent.

    An empty string is treated as "not set" so a key can be written out in
    the shipped `config.toml` (for documentation) without overriding the
    default until someone actually fills it in.
    """
    table = _FILE_CONFIG.get(section)
    if not isinstance(table, dict):
        return None
    value = table.get(key)
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _cfg_str(env: str, section: str, key: str, default: str) -> str:
    if env in os.environ:
        return os.environ[env]
    value = _file_value(section, key)
    return str(value) if value is not None else default


def _cfg_path(env: str, section: str, key: str, default: Path) -> Path:
    if env in os.environ:
        return Path(os.environ[env]).expanduser().resolve()
    value = _file_value(section, key)
    return Path(str(value)).expanduser().resolve() if value is not None else default


def _cfg_float(env: str, section: str, key: str, default: float, *, minimum: float | None = None) -> float:
    raw: Any = os.environ.get(env)
    if raw is None:
        raw = _file_value(section, key)
    if raw is None:
        result = float(default)
    else:
        try:
            result = float(raw)
        except (TypeError, ValueError):
            result = float(default)
    return max(minimum, result) if minimum is not None else result


def _cfg_int(env: str, section: str, key: str, default: int, *, minimum: int = 1) -> int:
    """An integer knob (worker/pool count, timeout). Clamped to ``minimum``
    (1 for a pool that must have at least one worker; 0 where "off"/"auto"
    is a meaningful value)."""
    raw: Any = os.environ.get(env)
    if raw is None:
        raw = _file_value(section, key)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


def _cfg_bool(env: str, section: str, key: str, default: bool) -> bool:
    raw = os.environ.get(env)
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes")
    value = _file_value(section, key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return default


# -- Paths ------------------------------------------------------------

#: Root of the on-disk, lazily-populated card cache (Scryfall data,
#: entirely disposable — deleting it just means the next lookup re-fetches
#: from Scryfall). Gitignored; see docs/Reference/08_CARD_CACHE_EXPORT_IMPORT.md.
CACHE_DIR = _cfg_path("MTG_CACHE_DIR", "paths", "cache_dir", _BACKEND_ROOT / "cache")

#: Root of on-disk, persistent application data (saved decks, player-
#: uploaded assets) — real user data with no upstream source to re-fetch,
#: unlike CACHE_DIR. Gitignored but NOT safe to delete.
DATA_DIR = _cfg_path("MTG_DATA_DIR", "paths", "data_dir", _BACKEND_ROOT / "data")

#: Default on-disk location for the lazily-populated card database.
DB_PATH = CACHE_DIR / "db" / "cards.db"

#: Default on-disk location for cached card images, keyed by Scryfall id
#: (see image_cache.py for the id-as-join-key layout).
IMAGE_CACHE_DIR = CACHE_DIR / "images"

#: Default on-disk location for saved decks.
DECKS_DB_PATH = DATA_DIR / "decks.db"

#: Default on-disk location for player-uploaded token art / sleeves.
PLAYER_ASSETS_DB_PATH = DATA_DIR / "player_assets.db"

# -- Scryfall -------------------------------------------------------

#: User-Agent sent to Scryfall — both api.scryfall.com and the
#: cards.scryfall.io image CDN 400 requests with no User-Agent.
USER_AGENT = _cfg_str("MTG_USER_AGENT", "scryfall", "user_agent", "MTG-Deck-Analyzer/0.1")

#: Minimum delay between Scryfall API requests. Scryfall asks integrations
#: to stay under ~10 requests/second; this is the simplest way to honor
#: that without a background rate limiter.
SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS = _cfg_float(
    "MTG_SCRYFALL_MIN_REQUEST_INTERVAL", "scryfall", "min_request_interval_seconds", 0.1, minimum=0.0
)

#: LazyCardLoader's loading policy for a name that's already cached (a name
#: that's never been cached at all is always fetched once, regardless of
#: this flag — there being no cached value to prefer isn't a policy
#: choice). False (default, "cache-primary"): an already-cached card is
#: served as-is even if it looks `stale` (missing mana-cost/image data, a
#: pre-fix `partner_with` reminder-text tail) rather than silently
#: refetched — the cache is authoritative once a name has ever resolved,
#: so an ordinary deck load never makes a surprise Scryfall call (and can't
#: hit its rate limit) just from browsing already-known cards. True
#: ("scryfall-primary"): today's original behavior — a stale row is always
#: refetched to prefer Scryfall's current data.
SCRYFALL_PRIMARY = _cfg_bool("MTG_SCRYFALL_PRIMARY", "scryfall", "primary", False)


# -- Logging ------------------------------------------------------------

#: Log level for the application's own loggers (everything under
#: `mtg_analyzer.*`). WARNING by default so an ordinary run stays quiet —
#: the engine and parser emit a lot of INFO. Raise it with
#: `MTG_LOG_LEVEL`, the config file's `logging.level`, or
#: `./start.sh --log info` (which also hands the same level to uvicorn as
#: `--log-level`, so its access log follows suit). `TRACE` is accepted for
#: parity with uvicorn and maps to `DEBUG` for the app's own loggers.
#: Applied in `api/app.py`'s `create_app()`.
LOG_LEVEL = _cfg_str("MTG_LOG_LEVEL", "logging", "level", "WARNING").upper()


# -- Multiplayer timers ---------------------------------------------

#: How long a multiplayer player may **hold priority without acting** before
#: the server closes their connection (`api/multiplayer_ws.py`'s sweeper).
#: The point isn't to police slow play — it's that a browser tab that went
#: away without a clean close still holds priority, and the game would
#: otherwise wait on it forever. Their seat is *not* lost immediately: they
#: become "disconnected", the server auto-passes for them so the table keeps
#: moving, and MULTIPLAYER_DISCONNECT_GRACE below decides how long they have
#: to come back. 0 disables the check entirely (useful for a table that
#: takes long breaks, and for tests).
MULTIPLAYER_IDLE_TIMEOUT_SECONDS = _cfg_float(
    "MTG_MULTIPLAYER_IDLE_TIMEOUT", "multiplayer", "idle_timeout_seconds", 120, minimum=0.0
)

#: How long a disconnected player's seat is held open. Reconnecting within
#: this window (same player name — see `services/lobby.py`) puts them back in
#: the same seat with the game as they left it; letting it lapse concedes
#: for them (RULE 104.3a), because a seat nobody is sitting in can't be
#: waited on forever. 0 disables the sweep, holding the seat indefinitely.
MULTIPLAYER_DISCONNECT_GRACE_SECONDS = _cfg_float(
    "MTG_MULTIPLAYER_DISCONNECT_GRACE", "multiplayer", "disconnect_grace_seconds", 90, minimum=0.0
)

#: How long the board's per-priority countdown (the shrinking progress bar in
#: the left rail) runs before it auto-passes for whoever holds priority. It
#: arms on every priority window a player *could* act in — a spell going on
#: the stack being the common one — and any interaction with the board (or the
#: explicit "interrupt" button) cancels it for that window. 0 disables it
#: entirely: priority is then only ever passed by hand. Only meaningful for
#: `interactive_priority` sessions (multiplayer / solo-vs-bots); a table can
#: override it in Setup (`LobbyGame.spell_timer_seconds`). The default is
#: deliberately generous — it also runs on your own turn, so a short value
#: would rush the active player.
MULTIPLAYER_SPELL_TIMER_SECONDS = _cfg_float(
    "MTG_MULTIPLAYER_SPELL_TIMER", "multiplayer", "spell_timer_seconds", 20, minimum=0.0
)

#: PLR-4: how long a browser's identity token (`services/lobby.py`'s
#: `LobbyPlayer.client_token`, minted client-side by profileView.js's
#: "Speichern" button into the `mtg_client_token` cookie) stays valid without
#: being used again. Sliding, not fixed — every reconnect that presents the
#: token renews it, mirroring the cookie's own sliding `Max-Age` — so a
#: browser in active use never expires and one that was abandoned (or had its
#: cookies cleared) quietly does, 90 days after it was last seen. This is
#: what lets the token disambiguate two browsers sharing a display name (the
#: thing PLR-4 is actually about) without ever needing real accounts.
CLIENT_TOKEN_VALIDITY_SECONDS = _cfg_float(
    "MTG_CLIENT_TOKEN_VALIDITY", "multiplayer", "client_token_validity_seconds", 90 * 24 * 3600, minimum=0.0
)


# -- Workers / concurrency ----------------------------------------------

#: Size of the server's blocking-request worker thread pool (Starlette /
#: AnyIO `to_thread`). Every gameplay endpoint — goldfish, replay,
#: multiplayer, dynamic-analysis start — is a synchronous `def`, so
#: FastAPI runs each in a pool thread and this is the ceiling on how many
#: run **at the same time**, i.e. how many independent games can be
#: mid-step in one process. The GIL still serializes pure-Python engine
#: work, but every request also does I/O (SQLite, Scryfall, WebSocket
#: sends) that releases it, and the engine yields often enough that
#: raising this measurably helps on multi-core hardware. Applied in
#: `api/app.py`'s lifespan via the AnyIO default thread limiter. Default
#: 40 matches AnyIO's own; raise it for a busy shared server.
SERVER_THREAD_WORKERS = _cfg_int("MTG_SERVER_THREAD_WORKERS", "workers", "server_threads", 40)

#: How many `DynamicAnalysisJob`s (headless goldfish-match batches) may be
#: *accepted and running* at once (`services/dynamic_analysis.py`'s
#: `_JobWorkerPool`). This is an admission cap, not a speed knob — a burst
#: of analysis requests queues here instead of each immediately spawning
#: threads/processes and fighting for cores. The per-job match
#: parallelism below is what makes a single analysis finish faster.
#: Default of 4 is conservative for this local-dev-scale app.
DYNAMIC_ANALYSIS_WORKERS = _cfg_int("MTG_DYNAMIC_ANALYSIS_WORKERS", "workers", "dynamic_analysis_workers", 4)

#: How many worker **processes** a single dynamic-analysis job fans its
#: independent match simulations across (`services/dynamic_analysis.py`'s
#: `run_dynamic_analysis`). Each simulated match is a self-contained,
#: CPU-bound pure-Python goldfish game, so spreading them over processes
#: is real, GIL-bypassing parallelism — this is the knob that actually
#: shortens an analysis. ``0`` means "one worker per CPU core"
#: (`os.cpu_count()`); ``1`` disables the pool and runs matches in-process
#: (lowest overhead for a small run). The effective count is additionally
#: capped at the match count, and small jobs always run in-process
#: regardless (`_MIN_MATCHES_FOR_PROCESS_POOL`) so a 3-match run doesn't
#: pay for interpreter spawns.
DYNAMIC_ANALYSIS_MATCH_WORKERS = _cfg_int(
    "MTG_DYNAMIC_ANALYSIS_MATCH_WORKERS", "workers", "dynamic_analysis_match_processes", 0, minimum=0
)
