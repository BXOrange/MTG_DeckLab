#!/usr/bin/env python3
"""Run the backend test suite with automatic stuck-test detection.

Per-test timeouts already come from `pytest.ini` (pytest-timeout), which
raises inside a hung test via SIGALRM and lets the suite continue — the
common case needs nothing beyond the documented `python -m pytest`
command; the failing test's own report names it directly
("Timeout (>20.0s) from pytest-timeout.").

This wrapper is the belt-and-suspenders path for the rarer hang
pytest-timeout can't reach on its own (a session-scoped fixture,
collection, or a C-level block that never returns to Python bytecode
for SIGALRM to land in, or the thread-method fallback on platforms
without SIGALRM, which aborts the whole process instead of just the one
test): a hard wall-clock ceiling on the *entire run* that kills the
process group and reports exactly which test was executing when it
fired, so a hang is diagnosed from one command instead of a dangling
prompt.

Resolves the backend venv itself (`setup/install.py`'s `ensure_backend_
venv`/`VENV_DIR` — the same "venv_win on Windows, venv elsewhere" switch
`start.sh`/`start.py` already use, see `VENV_DIR`'s docstring for why a
venv isn't relocatable across that split) rather than trusting whatever
interpreter launched this script, so it works the same run from any
shell — no "activate the venv first" step to get wrong or forget.

Usage (from backend/):
  python scripts/run_tests.py [--hard-timeout SECONDS] [pytest args...]
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT.parent / "setup"))
from install import ensure_backend_venv  # noqa: E402 (path must be set first)

TEST_NODE_RE = re.compile(r"^(tests/\S+::\S+)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hard-timeout",
        type=float,
        default=120.0,
        help="Overall wall-clock ceiling in seconds for the whole run "
        "(default: 120; the full suite normally runs in ~10s). Only "
        "fires if a hang isn't already caught by pytest-timeout's own "
        "per-test timer.",
    )
    args, pytest_args = parser.parse_known_args()

    python = ensure_backend_venv()
    cmd = [str(python), "-m", "pytest", "-v", *pytest_args]
    proc = subprocess.Popen(
        cmd,
        cwd=BACKEND_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,  # own process group, so a hard-timeout kill gets everything
    )

    last_test = "(collection / session setup -- no test had started yet)"
    killed = threading.Event()

    def kill_on_hard_timeout() -> None:
        killed.set()
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    watchdog = threading.Timer(args.hard_timeout, kill_on_hard_timeout)
    watchdog.daemon = True
    watchdog.start()

    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            match = TEST_NODE_RE.match(line.strip())
            if match:
                last_test = match.group(1)
        proc.wait()
    finally:
        watchdog.cancel()

    if killed.is_set():
        print(
            f"\nSTUCK TEST DETECTED: no result after {args.hard_timeout:.0f}s, "
            f"run killed. Last test that had started: {last_test}",
            file=sys.stderr,
        )
        return 124

    if proc.returncode is not None and proc.returncode < 0:
        print(
            f"\nSTUCK TEST DETECTED: pytest process was terminated (signal "
            f"{-proc.returncode}) -- see any thread dump above. Last test "
            f"that had started: {last_test}",
            file=sys.stderr,
        )
        return 124

    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
