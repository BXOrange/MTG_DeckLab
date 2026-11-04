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
  MTG_DYNAMIC_ANALYSIS_QUEUE_MAX / _QUEUE_MAX_PER_OWNER — waiting jobs in
    total / queued+running jobs per owner (refused past it, never evicted)
  MTG_DYNAMIC_ANALYSIS_RESULTS_PER_OWNER / _RESULT_TTL — finished results
    kept per owner / seconds they are kept
  MTG_SESSION_TTL / MTG_SESSION_MAX — idle seconds before a non-table game
    session is swept / max live sessions (BUG-43)
  MTG_LOBBY_MAX_PLAYERS / MTG_LOBBY_MAX_GAMES — lobby registration caps
  MTG_UPLOAD_MAX_BYTES — per-file sleeve/token upload limit (413 above)
  MTG_PLAYER_ASSET_MAX_COUNT / MTG_PLAYER_ASSET_MAX_BYTES — per-name upload quota
  MTG_PLAYER_ASSET_STORE_MAX_BYTES — whole asset-store byte cap (413 above)
  MTG_BUG_REPORT_MAX_COUNT / MTG_BUG_REPORT_MAX_BYTES — new bug reports are
    refused (never rotated) past these
  MTG_BIND_HOST — the `--host` address setup/start.py gave uvicorn (empty =
    loopback only); admitted in the Host/Origin allowlist (api/request_guard.py)
  MTG_ALLOWED_HOSTS — extra comma-separated Host names to accept (tests use
    `testserver`; empty by default)
  MTG_FRONTEND_ORIGIN — internal address the backend reverse-proxies
    non-/api//ws requests to (see FRONTEND_ORIGIN below); default
    http://127.0.0.1:8765, setup/start.py's static frontend server
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

#: Credentials, sessions, invitations (PLR-9a). Kept apart from decks.db so a
#: credential never shares a file with deck data (docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md §3).
ACCOUNTS_DB_PATH = DATA_DIR / "accounts.db"

#: Persistent Commander Spellbook combo snapshot; separate from the
#: disposable card cache so it can be refreshed and diffed in place.
COMMANDER_SPELLBOOK_DB_PATH = DATA_DIR / "commander_spellbook.db"

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

#: How long an MCP-controlled seat (`services/lobby.MCP_BOT_KIND`) may stay
#: silent before Smart Bot plays for it. The adapter's long-poll and every
#: action count as a sign of life; the window must outlast one slow LLM
#: "thinking" turn between two calls, or the seat would flap between the
#: client and the fallback. 0 means the seat never counts as connected.
MCP_SEAT_STALE_SECONDS = _cfg_float(
    "MTG_MCP_SEAT_STALE", "multiplayer", "mcp_seat_stale_seconds", 120, minimum=0.0
)

#: How long a disconnected player's seat is held open. Reconnecting within
#: this window (same account — see `services/lobby.py`) puts them back in
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

#: ANA-6: how many dynamic-analysis jobs may *wait* for a worker slot, server
#: wide. Past it a start is refused (503 `analysis_queue_full`), never
#: answered by evicting someone's job. 50 waiting jobs at the default 4 slots
#: is already minutes of work for a local-scale server.
DYNAMIC_ANALYSIS_QUEUE_MAX = _cfg_int("MTG_DYNAMIC_ANALYSIS_QUEUE_MAX", "limits", "dynamic_analysis_queue_max", 50)

#: ANA-6: queued + running jobs one owner (account or anonymous id) may have at
#: once; a fairness bound so one visitor cannot fill the queue (429
#: `analysis_owner_limit`). It does not cap finished results.
DYNAMIC_ANALYSIS_QUEUE_MAX_PER_OWNER = _cfg_int(
    "MTG_DYNAMIC_ANALYSIS_QUEUE_MAX_PER_OWNER", "limits", "dynamic_analysis_queue_max_per_owner", 3
)

#: ANA-6: finished results kept per owner; only that owner's own new results
#: roll their oldest off, other owners never evict it.
DYNAMIC_ANALYSIS_RESULTS_PER_OWNER = _cfg_int(
    "MTG_DYNAMIC_ANALYSIS_RESULTS_PER_OWNER", "limits", "dynamic_analysis_results_per_owner", 5
)

#: ANA-6: seconds a finished result is kept (from its finish) before the sweep
#: purges it; six hours covers "come back after a break" without growing forever.
DYNAMIC_ANALYSIS_RESULT_TTL_SECONDS = _cfg_int(
    "MTG_DYNAMIC_ANALYSIS_RESULT_TTL", "limits", "dynamic_analysis_result_ttl_seconds", 6 * 3600
)

#: ANA-6: `Retry-After` sent with a full-queue/owner-limit refusal; a typical
#: analysis finishes within about this long, so a retry then has a fair chance.
DYNAMIC_ANALYSIS_RETRY_AFTER_SECONDS = 30


# -- Frontend proxy -------------------------------------------------------

#: Internal address the backend reverse-proxies any request outside
#: `/api`/`/ws` to (`api/frontend_proxy.py`) — a plain server-to-server
#: HTTP call, invisible to and not subject to browser CORS. Lets a browser
#: reach the whole app through the backend's single port instead of two
#: origins. Default matches `setup/start.py`'s frontend static server
#: (`no_cache_server.py`, default port 8765); `run_servers()` overrides
#: this via MTG_FRONTEND_ORIGIN when `--port` picks a different one. Could
#: later point at a load balancer in front of several such processes —
#: that's a config change here, not a code change.
FRONTEND_ORIGIN = _cfg_str("MTG_FRONTEND_ORIGIN", "frontend", "origin", "http://127.0.0.1:8765")

#: `--host` as passed by setup/start.py; "" means uvicorn's loopback default.
BIND_HOST = _cfg_str("MTG_BIND_HOST", "server", "bind_host", "").strip()

#: Extra Host header names accepted besides loopback and BIND_HOST.
EXTRA_ALLOWED_HOSTS = tuple(
    h.strip() for h in _cfg_str("MTG_ALLOWED_HOSTS", "server", "allowed_hosts", "").split(",") if h.strip()
)

# -- Resource limits (BUG-43) --------------------------------------
# The app has no auth, so on a shared LAN every unbounded in-memory or
# on-disk collection is a denial-of-service lever. Defaults are far above
# what a normal table or user reaches; they only stop runaway clients.

#: How long a goldfish/solo/replay session may go untouched (no get/action)
#: before the sweeper drops it. A session also holds its undo history, so an
#: abandoned one is megabytes of RAM. Sessions a lobby table points at are
#: never expired on their own. The client sees the normal 404 afterwards.
GAME_SESSION_TTL_SECONDS = _cfg_float(
    "MTG_SESSION_TTL", "limits", "session_ttl_seconds", 6 * 60 * 60, minimum=1.0
)

#: Hard cap on live sessions. Creating one past the cap evicts the least
#: recently used session no lobby table needs; if every session is a table's,
#: the cap yields rather than killing a running game.
GAME_SESSION_MAX = _cfg_int("MTG_SESSION_MAX", "limits", "session_max", 200)

#: Anonymous visitors may play global decks (PLR-18), so their sessions are bounded on their
#: own: per anonymous id, and across all of them. Rotating the anonymous cookie therefore
#: cannot evict a logged-in player's session or exhaust memory; the oldest anonymous session
#: goes first. (There is no per-account cap: an account is a known, invited player.)
ANON_SESSION_MAX_PER_OWNER = _cfg_int("MTG_ANON_SESSION_MAX_PER_OWNER", "limits", "anon_session_max_per_owner", 5, minimum=1)
ANON_SESSION_MAX_TOTAL = _cfg_int("MTG_ANON_SESSION_MAX_TOTAL", "limits", "anon_session_max_total", 40, minimum=1)

#: Most distinct (non-bot) players the lobby registers at once.
LOBBY_MAX_PLAYERS = _cfg_int("MTG_LOBBY_MAX_PLAYERS", "limits", "lobby_max_players", 64)

#: Most tables (forming or running) the lobby holds at once.
LOBBY_MAX_GAMES = _cfg_int("MTG_LOBBY_MAX_GAMES", "limits", "lobby_max_games", 32)

#: Per-file upload ceiling for sleeves/token art; the body is read in chunks
#: and aborted as soon as this is exceeded (HTTP 413).
PLAYER_UPLOAD_MAX_BYTES = _cfg_int(
    "MTG_UPLOAD_MAX_BYTES", "limits", "upload_max_bytes", 5 * 1024 * 1024
)

#: Chunk size when reading an upload, so an oversized body is never held whole.
UPLOAD_READ_CHUNK_BYTES = 64 * 1024

#: Per-player-name quota across token images + sleeves (count and bytes).
PLAYER_ASSET_MAX_COUNT = _cfg_int("MTG_PLAYER_ASSET_MAX_COUNT", "limits", "player_asset_max_count", 100)
PLAYER_ASSET_MAX_TOTAL_BYTES = _cfg_int(
    "MTG_PLAYER_ASSET_MAX_BYTES", "limits", "player_asset_max_bytes", 100 * 1024 * 1024
)

#: Slack on top of PLAYER_UPLOAD_MAX_BYTES for the multipart envelope (boundary,
#: part headers, the label/token_name form field) when judging Content-Length.
UPLOAD_MULTIPART_OVERHEAD_BYTES = 64 * 1024

#: Whole-store cap on uploaded asset bytes. The per-name quota is bypassed by
#: rotating names (the app has no auth), so the store as a whole is bounded too.
#: Refused with 413 like the per-name quota (bug reports use 507 as a stored
#: directory, here the refusal is of the incoming upload).
PLAYER_ASSET_STORE_MAX_BYTES = _cfg_int(
    "MTG_PLAYER_ASSET_STORE_MAX_BYTES", "limits", "player_asset_store_max_bytes", 1024 * 1024 * 1024
)

#: Bug reports are the user's own evidence and are never auto-deleted, so the
#: cap is a refusal: once the directory holds this many reports (or bytes), a
#: new report is rejected (HTTP 507) until the user clears some by hand.
BUG_REPORT_MAX_COUNT = _cfg_int("MTG_BUG_REPORT_MAX_COUNT", "limits", "bug_report_max_count", 1000)
BUG_REPORT_MAX_TOTAL_BYTES = _cfg_int(
    "MTG_BUG_REPORT_MAX_BYTES", "limits", "bug_report_max_bytes", 500 * 1024 * 1024
)

# Persistent local bug reports, outside versioned documentation.
BUG_REPORT_DIR = _cfg_path(
    "MTG_BUG_REPORT_DIR", "paths", "bug_report_dir", _BACKEND_ROOT.parent / "bug-reports"
)


# -- Accounts (PLR-9a) ----------------------------------------------------
# Plan: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md. Nothing here is enforced on a
# real install before the PLR-9e cutover.

#: Shortest accepted player password (plan §3). Lower than OWASP's 15 for
#: password-only accounts, accepted for a trusted-network server: do not lower silently.
PASSWORD_MIN_LENGTH = _cfg_int("MTG_PASSWORD_MIN_LENGTH", "accounts", "password_min_length", 10, minimum=8)

#: Admin accounts need a longer password (plan §6).
ADMIN_PASSWORD_MIN_LENGTH = _cfg_int(
    "MTG_ADMIN_PASSWORD_MIN_LENGTH", "accounts", "admin_password_min_length", 15, minimum=10
)

#: Length from which a password earns "green" in the strength meter when it also has a
#: digit and a special character; shorter valid passwords are "yellow" (advisory only).
PASSWORD_GREEN_LENGTH = _cfg_int("MTG_PASSWORD_GREEN_LENGTH", "accounts", "password_green_length", 12, minimum=8)

#: Upper bound on a password before hashing, so a huge body cannot burn CPU/memory
#: in the hasher (OWASP: bound input size). Far above the 64 characters the plan requires.
PASSWORD_MAX_LENGTH = 1024

#: Account-name length bounds after normalisation (plan §1).
ACCOUNT_NAME_MIN_LENGTH = 3
ACCOUNT_NAME_MAX_LENGTH = 32

#: Server-side session lifetimes: idle (sliding) and absolute (plan §3).
SESSION_IDLE_SECONDS = _cfg_float("MTG_SESSION_IDLE_SECONDS", "accounts", "session_idle_seconds", 8 * 3600, minimum=60.0)
SESSION_ABSOLUTE_SECONDS = _cfg_float(
    "MTG_SESSION_ABSOLUTE_SECONDS", "accounts", "session_absolute_seconds", 14 * 24 * 3600, minimum=60.0
)

#: Invitation token lifetime (plan §3 *Invitations*).
INVITE_TTL_SECONDS = _cfg_float("MTG_INVITE_TTL_SECONDS", "accounts", "invite_ttl_seconds", 7 * 24 * 3600, minimum=60.0)

#: How many unredeemed, unexpired invitations one player may hold, and how many
#: they may create per rolling day. Admins are not capped (they are audited).
INVITE_MAX_OUTSTANDING_PER_PLAYER = _cfg_int("MTG_INVITE_MAX_OUTSTANDING", "accounts", "invite_max_outstanding", 5)
INVITE_MAX_PER_DAY_PER_PLAYER = _cfg_int("MTG_INVITE_MAX_PER_DAY", "accounts", "invite_max_per_day", 10)

#: How long a deleted/renamed account name stays unregistrable (plan §6).
NAME_TOMBSTONE_SECONDS = _cfg_float(
    "MTG_NAME_TOMBSTONE_DAYS", "accounts", "name_tombstone_days", 7.0, minimum=0.0
) * 24 * 3600

#: Lifetime of an OS-operator password-recovery credential (plan §6: expiring, single use).
RECOVERY_TTL_SECONDS = _cfg_float("MTG_RECOVERY_TTL_SECONDS", "accounts", "recovery_ttl_seconds", 3600.0, minimum=60.0)

#: Days a self-requested account deletion waits before the data is removed (plan section 6,
#: *Account deletion lifecycle*). The account is disabled at once; an admin can re-enable it on
#: `/admin` within this window, which cancels the deletion.
ACCOUNT_DELETION_GRACE_SECONDS = _cfg_float(
    "MTG_ACCOUNT_DELETION_GRACE_DAYS", "accounts", "account_deletion_grace_days", 7.0, minimum=0.0
) * 24 * 3600

#: How often the server looks for accounts whose deletion grace period has elapsed (it also runs
#: once at startup). Hourly is plenty against a grace period measured in days.
ACCOUNT_DELETION_SWEEP_SECONDS = 3600.0

# -- Data protection (PLR-9e) -----------------------------------------------
# Plan: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md section 7.

#: Environment variable holding the `accounts.db` key (64 hex characters = 256 random bits).
#: Deliberately env-only (never `config.json`, which is committed): a key must not live in a
#: file that travels with the repository or the data directory.
ACCOUNTS_DB_KEY_ENV = "MTG_ACCOUNTS_DB_KEY"

#: Key file used when the env var is unset: one line of 64 hex characters, mode 0600, **outside**
#: `MTG_DATA_DIR` (a copy of the data directory must not carry its own key). A home-directory
#: default works on macOS, Linux and Windows without an OS secret store (headless servers have none).
ACCOUNTS_DB_KEY_FILE = _cfg_path(
    "MTG_ACCOUNTS_DB_KEY_FILE", "accounts", "db_key_file", Path.home() / ".decklab" / "accounts.key"
)

#: Where `manage_accounts.py backup` writes encrypted copies of `accounts.db` by default.
ACCOUNTS_BACKUP_DIR = _cfg_path("MTG_ACCOUNTS_BACKUP_DIR", "accounts", "backup_dir", DATA_DIR / "backups")

#: Encrypted backups kept by `manage_accounts.py backup` (oldest managed ones are deleted beyond it).
ACCOUNTS_BACKUP_KEEP = _cfg_int("MTG_ACCOUNTS_BACKUP_KEEP", "accounts", "backup_keep", 14)

#: Retention of dead rows in `accounts.db` (plan section 7). Expired/revoked sessions and finished
#: recovery credentials only matter for a short forensic window; the audit log is kept longer
#: because restore runbooks read it (`player.deleted`). The hourly janitor deletes beyond these.
SESSION_RETENTION_SECONDS = _cfg_float(
    "MTG_SESSION_RETENTION_DAYS", "accounts", "session_retention_days", 7.0, minimum=0.0
) * 24 * 3600
RECOVERY_RETENTION_SECONDS = _cfg_float(
    "MTG_RECOVERY_RETENTION_DAYS", "accounts", "recovery_retention_days", 7.0, minimum=0.0
) * 24 * 3600
INVITATION_RETENTION_SECONDS = _cfg_float(
    "MTG_INVITATION_RETENTION_DAYS", "accounts", "invitation_retention_days", 30.0, minimum=0.0
) * 24 * 3600
AUDIT_RETENTION_SECONDS = _cfg_float(
    "MTG_AUDIT_RETENTION_DAYS", "accounts", "audit_retention_days", 365.0, minimum=1.0
) * 24 * 3600

#: Security-event log (`services/security_log.py`): a rotating file, separate from the application
#: log. An empty `MTG_SECURITY_LOG_FILE` disables the file (events still go to the logger).
SECURITY_LOG_FILE = _cfg_str("MTG_SECURITY_LOG_FILE", "logging", "security_log_file", str(DATA_DIR / "logs" / "security.log"))
#: Rotation: one file this large, this many rotated files kept (about 50 MB of history by default).
SECURITY_LOG_MAX_BYTES = _cfg_int("MTG_SECURITY_LOG_MAX_BYTES", "logging", "security_log_max_bytes", 5 * 1024 * 1024)
SECURITY_LOG_BACKUPS = _cfg_int("MTG_SECURITY_LOG_BACKUPS", "logging", "security_log_backups", 9)

# -- Administration (PLR-9d) ----------------------------------------------

#: Rows one admin list request may return (players, decks, audit log); bounds response size.
ADMIN_PAGE_MAX = 100

#: Finished admin jobs kept for progress inspection, and for how long after they ended their
#: poll token still works (it expires with the job, plan §6).
ADMIN_JOB_HISTORY_MAX = 20
ADMIN_JOB_RETENTION_SECONDS = 3600.0

#: Progress lines kept per job (the tail of the script output), each cut to the line length.
ADMIN_JOB_LOG_LINES = 40
ADMIN_JOB_LOG_LINE_MAX = 300

#: Upper bound on one decklist section a global-deck write may carry (characters).
ADMIN_DECK_TEXT_MAX = 200_000

#: Remote admin MFA (PLR-9d, plan section 6). TOTP per RFC 6238: 6 digits, 30 s step, HMAC-SHA1
#: (the algorithm every authenticator app implements by default).
TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30

#: Time steps either side of "now" a code is still accepted, absorbing clock drift between the
#: phone and the server (one step = 30 s each way). Replay protection still refuses a step that
#: was already used.
TOTP_SKEW_STEPS = 1

#: Single-use recovery codes issued with each enrolment, and their entropy (10 bytes = 80 bits).
ADMIN_RECOVERY_CODE_COUNT = 10
ADMIN_RECOVERY_CODE_BYTES = 10

#: The short-lived, server-held, request-bound grant that lets the admin page reuse one verified
#: authenticator code for many requests (a code is single-use per time step): idle and absolute
#: lifetime, and how many grants one admin may hold at once (oldest evicted). Held in memory
#: only, so a restart ends them; it travels in a header, never in a cookie.
ADMIN_GRANT_IDLE_SECONDS = 5 * 60.0
ADMIN_GRANT_ABSOLUTE_SECONDS = 30 * 60.0
ADMIN_GRANT_MAX_PER_ADMIN = 5

#: True when `setup/start.py --online --behind-tls-proxy` was chosen: a reverse proxy terminates
#: TLS, so the backend sees plain HTTP and trusts `X-Forwarded-Proto: https` from it. The operator
#: must make the backend reachable only through that proxy (SERVER_GUIDE section 2).
BEHIND_TLS_PROXY = _cfg_bool("MTG_BEHIND_TLS_PROXY", "server", "behind_tls_proxy", False)

#: Comma-separated CIDRs of the reverse proxies whose `X-Forwarded-Proto`/`X-Forwarded-For` the
#: backend believes (`--trusted-proxy`, BUG-52). Only meaningful with `BEHIND_TLS_PROXY`; the
#: default is a same-host proxy (loopback). Every other peer's forwarding headers are ignored.
TRUSTED_PROXIES = _cfg_str("MTG_TRUSTED_PROXIES", "server", "trusted_proxies", "127.0.0.0/8,::1/128")

#: Port of the dedicated loopback-only admin listener (PLR-19), served by the same process as the
#: main port. 0 = none. `setup/start.py --behind-tls-proxy` sets it (default: backend port + 1):
#: behind a proxy the main port cannot prove a request is local (BUG-52), this one can.
ADMIN_PORT = _cfg_int("MTG_ADMIN_PORT", "server", "admin_port", 0, minimum=0)

#: The admin listener binds this address only, never a configurable one: it exists to be unreachable
#: from the network.
ADMIN_LISTENER_HOST = "127.0.0.1"

#: Run mode (plan §1): "lan" (default), "online" (HTTPS only, `__Host-` cookie) or "localdev".
#: PLR-9a sets this from `setup/start.py --online/--localdev`; unknown values fall back to "lan".
RUN_MODE = _cfg_str("MTG_RUN_MODE", "server", "run_mode", "lan").strip().lower()
if RUN_MODE not in ("lan", "online", "localdev"):
    RUN_MODE = "lan"

#: Failed-login budget per window, counted per source address and per account name
#: (plan §3: throttle without an indefinite lockout — the window simply slides).
LOGIN_FAILURE_LIMIT = _cfg_int("MTG_LOGIN_FAILURE_LIMIT", "accounts", "login_failure_limit", 10)
LOGIN_FAILURE_WINDOW_SECONDS = _cfg_float(
    "MTG_LOGIN_FAILURE_WINDOW_SECONDS", "accounts", "login_failure_window_seconds", 15 * 60, minimum=1.0
)

#: Signup/invitation-redemption attempts per source and window (token guessing).
SIGNUP_ATTEMPT_LIMIT = _cfg_int("MTG_SIGNUP_ATTEMPT_LIMIT", "accounts", "signup_attempt_limit", 10)

#: True when `setup/start.py` chose a run mode explicitly (`--lan/--online/--localdev`). The
#: peer-address gate (`services/network_gate.py`) only runs then, so an app built directly
#: (tests, embedding) is not gated. PLR-9e flips `start.py`'s default to an explicit LAN mode.
RUN_MODE_EXPLICIT = "MTG_RUN_MODE" in os.environ

#: Operator CIDRs reachable in LAN mode, e.g. "192.168.179.0/24,10.8.0.0/16". When set it is
#: the complete list (loopback is always added); when empty the host's interface subnets apply.
ALLOWED_NETWORKS = _cfg_str("MTG_ALLOWED_NETWORKS", "server", "allowed_networks", "")
