#!/usr/bin/env python3
r"""Cross-platform install routine for MTG Deck Analyzer.

Creates the backend's virtual environment (if missing) and installs its
dependencies. Pure standard library, works the same on macOS/Linux/Windows
as long as a Python 3 interpreter is on PATH.

**Offline startup.** `start.py` calls `ensure_backend_venv()` on every run,
so anything this module does is part of "starting the app". It therefore
tries hard to need no network:

* Requirements are installed **offline first** (`pip install --no-index`,
  see `_pip_install`). With the venv already populated that resolves
  entirely from what's installed — pip makes no request at all — so a
  normal start works with the network unplugged. Only if that fails (a
  missing or too-old dependency) is a second, index-using attempt made.
* Wheels can be cached locally so even a *fresh* venv can be built
  offline: `python3 setup/install.py --download-wheels` while online fills
  `setup/wheels/` (the "wheelhouse"), and every later install passes
  `--find-links` at it. This is the only piece of the app that genuinely
  needs the internet on a fresh checkout — card data and images are
  cached by the backend itself (`backend/cache/`), and the frontend
  loads no external script, stylesheet or font.
* `pip install --upgrade pip` is *not* run unconditionally any more: it
  always queries PyPI, which made every single start depend on the
  network. It now runs only right after creating a brand-new venv, and
  its failure is not fatal.

Usage:
  python3 setup/install.py      (macOS/Linux)
  python setup\install.py       (Windows)
  python3 setup/install.py --download-wheels   (cache wheels for offline installs)
"""

import argparse
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
#: Windows gets its own venv directory rather than sharing "venv": a venv
#: is not relocatable/cross-platform (its activation scripts and bundled
#: pip hardcode the interpreter's own layout), so a venv created by
#: install.sh under WSL/macOS/Linux has a "bin/" layout that a native
#: Windows Python can't use (it needs "Scripts/"). Keeping them apart
#: means switching between a WSL shell and a native Windows shell in the
#: same checkout never corrupts either venv.
VENV_DIR = BACKEND_DIR / ("venv_win" if sys.platform == "win32" else "venv")
REQUIREMENTS = BACKEND_DIR / "requirements.txt"

#: Local wheel cache used with `pip --find-links` so a venv can be created
#: without network access. Populated by `--download-wheels` (gitignored —
#: wheels are platform/Python-version specific, so they're a local cache,
#: not something to commit).
WHEELHOUSE = ROOT / "setup" / "wheels"

#: Host probed to decide whether an index-using pip run is worth
#: attempting at all. Only consulted when the offline install failed, so a
#: normal start never opens this socket.
_PYPI_HOST = "pypi.org"
_PYPI_PORT = 443


def venv_python(venv_dir: Path) -> Path:
    """Path to a venv's python executable, cross-platform."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def activate_hint() -> str:
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "activate.bat")
    return f"source {VENV_DIR / 'bin' / 'activate'}"


def wheelhouse_args(wheelhouse: Path = WHEELHOUSE) -> list[str]:
    """`--find-links` pointing at the local wheel cache, if it has wheels."""
    if wheelhouse.is_dir() and any(wheelhouse.glob("*.whl")):
        return ["--find-links", str(wheelhouse)]
    return []


def network_available(host: str = _PYPI_HOST, port: int = _PYPI_PORT, timeout: float = 2.0) -> bool:
    """Whether a TCP connection to the package index can be opened.

    A plain connect attempt rather than a pip run: pip retries for tens of
    seconds before giving up, which would turn "no internet" into a long
    stall on every start.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pip_install(python: Path, *extra_args: str, offline: bool, quiet: bool = False) -> int:
    """Run `pip install -r requirements.txt`; return its exit code.

    `offline=True` adds `--no-index`, which makes pip resolve purely from
    what is already installed plus the wheelhouse — guaranteed to open no
    connection, and fast (~0.2s) when everything is already satisfied.
    """
    command = [
        str(python), "-m", "pip", "install",
        # Never let pip's own "a new release is available" check reach out.
        "--disable-pip-version-check",
        "--no-input",
    ]
    if quiet:
        command.append("--quiet")
    if offline:
        command.append("--no-index")
    command += wheelhouse_args()
    command += list(extra_args)
    command += ["-r", str(REQUIREMENTS)]
    return subprocess.run(command).returncode


def ensure_backend_venv(python_executable: str | None = None, recreate: bool = False) -> Path:
    """Create the backend venv if missing and install its requirements.

    Returns the path to the venv's python executable. Makes no network
    request when the venv already satisfies `requirements.txt` — see this
    module's docstring.
    """
    python_executable = python_executable or sys.executable

    if recreate and VENV_DIR.exists():
        print(f"Removing existing virtual environment at {VENV_DIR} ...")
        shutil.rmtree(VENV_DIR)

    fresh_venv = not VENV_DIR.exists()
    if fresh_venv:
        print(f"Creating virtual environment in {VENV_DIR} using {python_executable} ...")
        # `venv` bootstraps pip from the interpreter's bundled ensurepip,
        # so this step is itself offline-safe.
        subprocess.run([python_executable, "-m", "venv", str(VENV_DIR)], check=True)

    python = venv_python(VENV_DIR)

    if fresh_venv and network_available():
        # Only on a brand-new venv, and never fatal: a venv's bundled pip
        # can be old enough to miss newer wheel tags, but that's a
        # nice-to-have, not a reason to fail a start.
        subprocess.run(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check",
             "--upgrade", "pip"],
            check=False,
        )

    # Attempt 1 — offline. Succeeds (silently, in a fraction of a second)
    # whenever the venv is already complete, which is the normal case on
    # every start after the first.
    if _pip_install(python, offline=True, quiet=True) == 0:
        return python

    print("Backend dependencies are missing or outdated; installing ...")
    if not network_available():
        raise RuntimeError(
            "Backend dependencies are not installed and there is no connection to "
            f"{_PYPI_HOST}.\n"
            "To install them without internet access, run this once on a machine "
            "that has it (same OS and Python version):\n"
            "    python3 setup/install.py --download-wheels\n"
            f"and copy the resulting {WHEELHOUSE} directory here."
        )

    if _pip_install(python, offline=False) != 0:
        raise RuntimeError(
            f"Installing {REQUIREMENTS} failed. See the pip output above."
        )
    return python


def download_wheels(python: Path, destination: Path = WHEELHOUSE) -> None:
    """Cache every requirement as a wheel for later offline installs.

    Wheels are specific to this OS/architecture/Python version, which is
    why they're a local cache rather than a committed directory.
    """
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading dependency wheels into {destination} ...")
    subprocess.run(
        [str(python), "-m", "pip", "download", "--disable-pip-version-check",
         "-r", str(REQUIREMENTS), "-d", str(destination)],
        check=True,
    )
    count = len(list(destination.glob("*.whl")))
    print(f"Wheelhouse ready: {count} wheel(s) in {destination}")
    print("A fresh backend venv can now be created without an internet connection.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the backend virtual environment and install dependencies.")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use for venv creation")
    parser.add_argument("--recreate-venv", action="store_true", help="Delete an existing backend venv before reinstalling")
    parser.add_argument(
        "--download-wheels",
        action="store_true",
        help=(
            "Additionally cache every dependency as a wheel in setup/wheels/ so a "
            "later install (or a fresh venv) works without an internet connection."
        ),
    )
    args = parser.parse_args()

    python = ensure_backend_venv(python_executable=args.python, recreate=args.recreate_venv)

    if args.download_wheels:
        print()
        download_wheels(python)

    print()
    print(f"Done. Backend virtual environment ready at: {VENV_DIR}")
    print("Activate it with:")
    print(f"  {activate_hint()}")
    print()
    print("Run this to start the app:")
    print("  python3 setup/start.py   (macOS/Linux)")
    print("  python setup\\start.py    (Windows)")


if __name__ == "__main__":
    main()
