#!/usr/bin/env python3
r"""Cross-platform start routine for MTG Deck Analyzer.

Ensures the backend virtual environment is set up (so a single
`start.py` call works on a fresh checkout without running install.py
first) and starts both the backend API server (uvicorn) and the
frontend static server. Pure standard library, works the same on
macOS/Linux/Windows as long as a Python 3 interpreter is on PATH.

Usage:
  python3 setup/start.py  [--port 8765] [--backend-port 8000] [--backend-tests] [--no-browser] [--scryfall-primary]
  python setup\start.py   [--port 8765] [--backend-port 8000] [--backend-tests] [--no-browser] [--scryfall-primary]
"""

import argparse
import os
import signal
import socket
import subprocess
import sys
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


def start_backend(python, port: int, scryfall_primary: bool = False) -> subprocess.Popen:
    print(f"Starting backend API at http://localhost:{port} ...")
    env = os.environ.copy()
    if scryfall_primary:
        # See mtg_analyzer/config.py's SCRYFALL_PRIMARY: switches
        # LazyCardLoader from the default cache-primary loading policy to
        # always refetching a stale cached card from Scryfall.
        env["MTG_SCRYFALL_PRIMARY"] = "1"
    return subprocess.Popen(
        [str(python), "-m", "uvicorn", "mtg_analyzer.api.app:app", "--port", str(port)],
        cwd=str(BACKEND_DIR),
        env=env,
    )


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def start_frontend(port: int, open_browser: bool) -> subprocess.Popen:
    url = f"http://localhost:{port}"
    print(f"Starting frontend at {url} (Ctrl+C to stop) ...")
    # A custom no-cache server, not the stdlib `http.server` module
    # directly: plain http.server sends no Cache-Control header, so
    # browsers can serve a stale cached copy on a normal reload after a
    # file changes (see setup/no_cache_server.py).
    frontend_proc = subprocess.Popen(
        [sys.executable, str(NO_CACHE_SERVER), str(port)], cwd=str(FRONTEND_DIR)
    )

    if open_browser:
        if not wait_for_port("127.0.0.1", port):
            # Don't leave the just-spawned server running as an orphan that
            # blocks this same port on the next attempt.
            _stop(frontend_proc)
            raise RuntimeError(f"Frontend server did not become ready on port {port}.")
        webbrowser.open(url)

    return frontend_proc


def run_servers(python, port: int, backend_port: int, open_browser: bool, scryfall_primary: bool = False) -> None:
    backend_proc = start_backend(python, backend_port, scryfall_primary=scryfall_primary)
    try:
        if not wait_for_port("127.0.0.1", backend_port):
            raise RuntimeError(f"Backend API did not become ready on port {backend_port}.")

        frontend_proc = start_frontend(port, open_browser=open_browser)

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
    parser = argparse.ArgumentParser(description="Start MTG Deck Analyzer.")
    parser.add_argument("--port", type=int, default=8765, help="Frontend server port (default: 8765)")
    parser.add_argument("--backend-port", type=int, default=8000, help="Backend API port (default: 8000)")
    parser.add_argument("--backend-tests", action="store_true", help="Run the backend pytest suite first")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    parser.add_argument("--backend-only", action="store_true", help="Start the backend API without the frontend server")
    parser.add_argument("--frontend-only", action="store_true", help="Start the frontend server without the backend API")
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
    args = parser.parse_args()

    if args.backend_only and args.frontend_only:
        parser.error("--backend-only and --frontend-only cannot be used together")

    print("Ensuring backend virtual environment is set up ...")
    python = ensure_backend_venv()
    print()

    if args.backend_tests:
        run_backend_tests(python)
        print()

    if args.backend_only:
        backend_proc = start_backend(python, args.backend_port, scryfall_primary=args.scryfall_primary)
        try:
            backend_proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            _stop(backend_proc)
        return

    if args.frontend_only:
        frontend_proc = start_frontend(args.port, open_browser=not args.no_browser)
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
    )


if __name__ == "__main__":
    main()
