#!/usr/bin/env python3
r"""Cross-platform start routine for MTG Deck Analyzer.

Ensures the backend virtual environment is set up (so a single
`start.py` call works on a fresh checkout without running install.py
first) and starts the frontend static server. The backend has no HTTP
server yet (see backend/TODO.md) — once it exists, this is the place to
launch it alongside the frontend. Pure standard library, works the same
on macOS/Linux/Windows as long as a Python 3 interpreter is on PATH.

Usage:
  python3 setup/start.py  [--port 8765] [--backend-tests] [--no-browser]
  python setup\start.py   [--port 8765] [--backend-tests] [--no-browser]
"""

import argparse
import signal
import subprocess
import sys
import time
import webbrowser

from install import BACKEND_DIR, ROOT, ensure_backend_venv

FRONTEND_DIR = ROOT / "frontend"


def run_backend_tests(python) -> None:
    print("Running backend tests ...")
    subprocess.run([str(python), "-m", "pytest", "tests/"], cwd=str(BACKEND_DIR), check=True)


def start_frontend(port: int, open_browser: bool) -> None:
    url = f"http://localhost:{port}"
    print(f"Starting frontend at {url} (Ctrl+C to stop) ...")
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port)], cwd=str(FRONTEND_DIR))

    # A plain `except KeyboardInterrupt` only covers Ctrl+C (SIGINT).
    # Without this, SIGTERM (e.g. a process manager or IDE stop button)
    # kills this script immediately and leaves the http.server child
    # running as an orphan. Route SIGTERM through the same cleanup path.
    def handle_sigterm(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_sigterm)

    if open_browser:
        time.sleep(0.5)
        webbrowser.open(url)

    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start MTG Deck Analyzer.")
    parser.add_argument("--port", type=int, default=8765, help="Frontend server port (default: 8765)")
    parser.add_argument("--backend-tests", action="store_true", help="Run the backend pytest suite first")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    args = parser.parse_args()

    print("Ensuring backend virtual environment is set up ...")
    python = ensure_backend_venv()
    print()

    if args.backend_tests:
        run_backend_tests(python)
        print()

    print("Note: the backend has no HTTP server yet (see backend/TODO.md);")
    print("only the frontend static server is started.")
    print()
    start_frontend(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
