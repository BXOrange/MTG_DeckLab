#!/usr/bin/env python3
r"""Cross-platform start routine for DeckLab.

Ensures the backend virtual environment is set up (so a single
`start.py` call works on a fresh checkout without running install.py
first) and starts both the backend API server (uvicorn) and the
frontend static server. Pure standard library, works the same on
macOS/Linux/Windows as long as a Python 3 interpreter is on PATH.

Usage:
  python3 setup/start.py  [--port 8765] [--backend-port 8000] [--backend-tests] [--no-browser] [--scryfall-primary] [--host HOST]
  python setup\start.py   [--port 8765] [--backend-port 8000] [--backend-tests] [--no-browser] [--scryfall-primary] [--host HOST]

  --log LEVEL             backend log level (app loggers + uvicorn);
                         default "warning"
  --host HOST             backend bind address (uvicorn --host); default
                         omitted = loopback-only. Pass 0.0.0.0 to reach the
                         app from other computers on the network — this app
                         has NO authentication, see --help.

Worker/concurrency knobs (each also has a matching MTG_* env var and a
key in backend/mtg_analyzer/config.json; the flag wins over both):
  --server-threads N          how many games may be mid-step at once in the
                              one backend process (default 40)
  --analysis-jobs N           how many dynamic-analysis jobs run at once
  --analysis-match-workers N  worker processes ONE analysis job spreads its
                              matches across for real speed-up (0 = one per
                              CPU core, 1 = in-process)
"""

import argparse
import os
import signal
import socket
import subprocess
import time
import webbrowser
from contextlib import closing

from install import BACKEND_DIR, ROOT, ensure_backend_venv

FRONTEND_DIR = ROOT / "frontend"
NO_CACHE_SERVER = ROOT / "setup" / "no_cache_server.py"


def run_backend_tests(python) -> None:
    print("Running backend tests ...")
    subprocess.run([str(python), "-m", "pytest", "tests/"], cwd=str(BACKEND_DIR), check=True)


def wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.2)
    return False


def _detect_lan_ip() -> str | None:
    """Best-effort local-network IP for the "open this from another
    computer" message. The standard trick: a UDP socket's connect() never
    actually sends a packet (UDP is connectionless) — it just makes the OS
    pick the local address it would route a public destination through,
    which getsockname() then reads back. Never allowed to block or fail
    startup: any error here just means the message falls back to printing
    the raw --host value instead of a concrete IP.
    """
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


#: Loopback addresses uvicorn's own --host would also treat as local-only;
#: used only to decide whether the "reachable from this network" warning
#: below applies, not to validate --host itself (uvicorn does that).
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def start_backend(
    python, port: int, scryfall_primary: bool = False, extra_env=None, log_level: str = "warning",
    frontend_origin: str | None = None, host: str | None = None,
) -> subprocess.Popen:
    print(f"Starting backend API at http://localhost:{port} ...")
    if host is not None and host not in _LOOPBACK_HOSTS:
        # This app has no authentication (see CLAUDE.md) — anyone who can
        # reach this host/port can read and write saved decks, player
        # uploads, and play in any game. --host is opt-in for exactly this
        # reason; make the consequence explicit rather than silent.
        lan_ip = _detect_lan_ip()
        reachable_at = f"http://{lan_ip}:{port}" if lan_ip else f"http://{host}:{port}"
        print(
            f"WARNING: backend is reachable from the network at {reachable_at} "
            "with no authentication."
        )
    env = os.environ.copy()
    if scryfall_primary:
        # See mtg_analyzer/config.py's SCRYFALL_PRIMARY: switches
        # LazyCardLoader from the default cache-primary loading policy to
        # always refetching a stale cached card from Scryfall.
        env["MTG_SCRYFALL_PRIMARY"] = "1"
    if frontend_origin is not None:
        # Tells the backend's catch-all proxy (api/frontend_proxy.py) where
        # the frontend static server actually landed, in case --port picked
        # something other than config.py's built-in default (8765).
        env["MTG_FRONTEND_ORIGIN"] = frontend_origin
    # Worker knobs (--server-threads / --analysis-jobs /
    # --analysis-match-workers) are passed to the app as MTG_* env vars,
    # read by mtg_analyzer/config.py. See main().
    for key, value in (extra_env or {}).items():
        env[key] = str(value)
    # A single uvicorn process on purpose — no `--workers N`. The game
    # session manager, the multiplayer lobby and the dynamic-analysis job
    # registry are all in-memory, process-wide singletons
    # (api/dependencies.py), so a second worker process would not see a
    # session created on the first. Concurrency within the one process is
    # via the request thread pool (--server-threads) and, for analysis, a
    # per-job process pool (--analysis-match-workers).
    # `--log-level` defaults to "warning" here rather than uvicorn's own
    # "info": a normal run is quiet, and `--log` raises both this and the
    # app's `mtg_analyzer.*` loggers (via MTG_LOG_LEVEL, see main()).
    cmd = [
        str(python), "-m", "uvicorn", "mtg_analyzer.api.app:app",
        "--port", str(port), "--log-level", str(log_level),
    ]
    if host is not None:
        # Omitted entirely (not just left at a default) when the caller
        # doesn't ask for it, so uvicorn's own default (127.0.0.1,
        # loopback-only) applies untouched — this flag only ever widens
        # reachability, never narrows or changes it by default.
        cmd += ["--host", host]
    return subprocess.Popen(cmd, cwd=str(BACKEND_DIR), env=env)


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def start_frontend(python, port: int, open_browser: bool) -> subprocess.Popen:
    url = f"http://localhost:{port}"
    if open_browser:
        # --frontend-only: this IS the URL to open (no backend proxy in front of it).
        print(f"Starting frontend at {url} (Ctrl+C to stop) ...")
    else:
        # Combined run: the backend proxies to this port (api/frontend_proxy.py);
        # nothing should open it directly, see run_servers().
        print(f"Starting frontend (internal, proxied by the backend) at {url} ...")
    # A custom no-cache server, not the stdlib `http.server` module
    # directly: plain http.server sends no Cache-Control header, so
    # browsers can serve a stale cached copy on a normal reload after a
    # file changes (see setup/no_cache_server.py).
    #
    # Uses the same venv `python` as the backend rather than
    # `sys.executable` (whatever launched this script): on macOS, a
    # process's permission to accept incoming local connections is
    # granted per binary identity, and the venv python is the one
    # already proven trusted by the backend server above. Spawning the
    # frontend under a different, unapproved python binary can leave it
    # silently unreachable (socket bound, but the OS drops incoming
    # connections) with no error from the child — which then looks like
    # this server simply "never becomes ready".
    frontend_proc = subprocess.Popen(
        [str(python), str(NO_CACHE_SERVER), str(port)], cwd=str(FRONTEND_DIR)
    )

    if open_browser:
        if not wait_for_port("127.0.0.1", port):
            # Don't leave the just-spawned server running as an orphan that
            # blocks this same port on the next attempt.
            _stop(frontend_proc)
            raise RuntimeError(f"Frontend server did not become ready on port {port}.")
        webbrowser.open(url)

    return frontend_proc


def run_servers(
    python, port: int, backend_port: int, open_browser: bool, scryfall_primary: bool = False,
    extra_env=None, log_level: str = "warning", host: str | None = None,
) -> None:
    # The backend proxies non-/api//ws requests to the frontend (see
    # api/frontend_proxy.py), so it's the only port a browser needs to
    # reach — tell it exactly where the frontend landed, since --port can
    # move that away from config.py's built-in default. The frontend
    # process itself always stays loopback-only regardless of --host: only
    # the backend needs to be reachable beyond this machine now.
    backend_proc = start_backend(
        python, backend_port, scryfall_primary=scryfall_primary, extra_env=extra_env, log_level=log_level,
        frontend_origin=f"http://127.0.0.1:{port}", host=host,
    )
    try:
        if not wait_for_port("127.0.0.1", backend_port):
            raise RuntimeError(f"Backend API did not become ready on port {backend_port}.")

        # open_browser=False here even when the caller wants a browser
        # opened: the frontend is now an internal proxy target, not
        # something to open directly — see the webbrowser.open() call below,
        # once both servers (and the proxy path between them) are ready.
        frontend_proc = start_frontend(python, port, open_browser=False)

        if open_browser:
            if not wait_for_port("127.0.0.1", port):
                _stop(frontend_proc)
                raise RuntimeError(f"Frontend server did not become ready on port {port}.")
            webbrowser.open(f"http://localhost:{backend_port}")

        # A plain `except KeyboardInterrupt` only covers Ctrl+C (SIGINT).
        # Without this, SIGTERM (e.g. a process manager or IDE stop button)
        # kills this script immediately and leaves the child processes
        # running as orphans. Route SIGTERM through the same cleanup path.
        def handle_sigterm(_signum, _frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, handle_sigterm)

        try:
            frontend_proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            _stop(frontend_proc)
            _stop(backend_proc)
    except Exception as exc:
        print(f"Startup failed: {exc}")
        _stop(backend_proc)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Start DeckLab.")
    parser.add_argument("--port", type=int, default=8765, help="Frontend server port (default: 8765)")
    parser.add_argument("--backend-port", type=int, default=8000, help="Backend API port (default: 8000)")
    parser.add_argument("--backend-tests", action="store_true", help="Run the backend pytest suite first")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    parser.add_argument("--backend-only", action="store_true", help="Start the backend API without the frontend server")
    parser.add_argument("--frontend-only", action="store_true", help="Start the frontend server without the backend API")
    parser.add_argument(
        "--host",
        default=None,
        metavar="HOST",
        help=(
            "Backend bind address, passed straight through as uvicorn's own --host. "
            "Default: omitted, so uvicorn's own loopback-only default (127.0.0.1) "
            "applies — the app is reachable only from this machine. Pass 0.0.0.0 to "
            "make it reachable from other computers on the network. This app has NO "
            "authentication (see CLAUDE.md): anyone who can reach the host/port can "
            "read and write saved decks, player uploads, and play in any game. "
            "The frontend static server (setup/no_cache_server.py) always stays "
            "loopback-only regardless of this flag — the backend proxies it "
            "internally, so only the backend needs to be reachable beyond this "
            "machine (see api/frontend_proxy.py)."
        ),
    )
    parser.add_argument(
        "--scryfall-primary",
        action="store_true",
        help=(
            "Always refetch a stale cached card from Scryfall instead of serving it "
            "as-is (this project's original behavior). Default is cache-primary: an "
            "already-cached card is never auto-refetched, avoiding surprise Scryfall "
            "calls (and rate limits) on an ordinary deck load."
        ),
    )
    parser.add_argument(
        "--log",
        default=None,
        metavar="LEVEL",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help=(
            "Backend log level for both the app's own loggers and uvicorn. "
            "Default: warning (quiet). Use 'info' or 'debug' to see engine/parser detail."
        ),
    )
    # Worker/concurrency knobs. Each maps to an MTG_* env var read by
    # mtg_analyzer/config.py, and overrides both backend/mtg_analyzer/
    # config.json and the built-in default. Left unset here, the file /
    # default decide.
    parser.add_argument(
        "--server-threads", type=int, default=None, metavar="N",
        help="How many blocking requests (i.e. games mid-step) the backend handles at once (default 40).",
    )
    parser.add_argument(
        "--analysis-jobs", type=int, default=None, metavar="N",
        help="How many dynamic-analysis jobs run concurrently (admission cap, default 4).",
    )
    parser.add_argument(
        "--analysis-match-workers", type=int, default=None, metavar="N",
        help=(
            "Worker processes ONE dynamic-analysis job spreads its independent match "
            "simulations across (real speed-up). 0 = one per CPU core, 1 = in-process."
        ),
    )
    args = parser.parse_args()

    worker_env = {}
    if args.server_threads is not None:
        worker_env["MTG_SERVER_THREAD_WORKERS"] = args.server_threads
    if args.analysis_jobs is not None:
        worker_env["MTG_DYNAMIC_ANALYSIS_WORKERS"] = args.analysis_jobs
    if args.analysis_match_workers is not None:
        worker_env["MTG_DYNAMIC_ANALYSIS_MATCH_WORKERS"] = args.analysis_match_workers

    # No --log: uvicorn is quieted to "warning" (vs its own "info" default)
    # and the app's own loggers keep their config.json / WARNING default.
    # With --log: force both to that level (MTG_LOG_LEVEL wins over the file).
    log_level = args.log or "warning"
    if args.log is not None:
        worker_env["MTG_LOG_LEVEL"] = args.log

    if args.backend_only and args.frontend_only:
        parser.error("--backend-only and --frontend-only cannot be used together")

    print("Ensuring backend virtual environment is set up ...")
    python = ensure_backend_venv()
    print()

    if args.backend_tests:
        run_backend_tests(python)
        print()

    if args.backend_only:
        backend_proc = start_backend(
            python, args.backend_port, scryfall_primary=args.scryfall_primary,
            extra_env=worker_env, log_level=log_level, host=args.host,
        )
        try:
            backend_proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            _stop(backend_proc)
        return

    if args.frontend_only:
        frontend_proc = start_frontend(python, args.port, open_browser=not args.no_browser)
        try:
            frontend_proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            _stop(frontend_proc)
        return

    run_servers(
        python, args.port, args.backend_port,
        open_browser=not args.no_browser, scryfall_primary=args.scryfall_primary,
        extra_env=worker_env, log_level=log_level, host=args.host,
    )


if __name__ == "__main__":
    main()
