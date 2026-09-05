#!/usr/bin/env python3
r"""Install development-only test and lint tooling.

This is intentionally separate from ``install.py``: users who only run the
application never download Node, ESLint, or nodeenv.  The script creates a
project-local Node runtime in ``frontend/.nodeenv`` and installs frontend
packages in ``frontend/node_modules``.  Both paths are gitignored.

Usage:
  python3 setup/install_dev.py       (macOS/Linux)
  python setup\install_dev.py        (Windows)
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from install import ensure_backend_venv, VENV_DIR


ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
DEV_REQUIREMENTS = BACKEND_DIR / "requirements-dev.txt"
NODEENV_DIR = FRONTEND_DIR / ".nodeenv"
# Kept explicit so every developer gets the same local Node major version.
NODE_VERSION = "22.14.0"


def _nodeenv_executable() -> Path:
    return NODEENV_DIR / ("Scripts/nodeenv.exe" if sys.platform == "win32" else "bin/nodeenv")


def _npm_executable() -> Path:
    return NODEENV_DIR / ("Scripts/npm.cmd" if sys.platform == "win32" else "bin/npm")


def _install_dev_python_packages(python: Path) -> None:
    if subprocess.run(
        [str(python), "-c", "import nodeenv"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
         "-r", str(DEV_REQUIREMENTS)],
        check=True,
    )


def _install_local_node(python: Path, recreate: bool) -> None:
    if _npm_executable().exists() and not recreate:
        return
    # nodeenv's --force replaces only this explicitly named local runtime.
    force = ["--force"] if NODEENV_DIR.exists() else []
    subprocess.run(
        [str(python), "-m", "nodeenv", "--node", NODE_VERSION, "--prebuilt", *force, str(NODEENV_DIR)],
        check=True,
    )


def _install_frontend_packages() -> None:
    npm = _npm_executable()
    if not npm.exists():
        raise RuntimeError(f"The project-local npm executable was not created at {npm}.")
    eslint = FRONTEND_DIR / "node_modules" / ".bin" / ("eslint.cmd" if sys.platform == "win32" else "eslint")
    if eslint.exists():
        return
    environment = os.environ.copy()
    environment["PATH"] = str(npm.parent) + os.pathsep + environment.get("PATH", "")
    subprocess.run([str(npm), "install", "--no-audit", "--no-fund"], cwd=FRONTEND_DIR, env=environment, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install development-only test and lint tooling.")
    parser.add_argument("--recreate-nodeenv", action="store_true", help="Replace frontend/.nodeenv before installing Node.")
    parser.add_argument("--skip-frontend", action="store_true", help="Install only Python development tooling.")
    args = parser.parse_args()

    python = ensure_backend_venv()
    print("Installing Python development tools ...")
    _install_dev_python_packages(python)

    if not args.skip_frontend:
        print(f"Installing project-local Node {NODE_VERSION} in {NODEENV_DIR} ...")
        _install_local_node(python, args.recreate_nodeenv)
        print("Installing frontend development packages ...")
        _install_frontend_packages()

    print("\nDevelopment environment ready.")
    print(f"  Python environment: {VENV_DIR}")
    if not args.skip_frontend:
        print(f"  Node environment:   {NODEENV_DIR}")
        print("  Run frontend lint:  (cd frontend && PATH=\"$PWD/.nodeenv/bin:$PATH\" .nodeenv/bin/npm run lint)")


if __name__ == "__main__":
    main()
