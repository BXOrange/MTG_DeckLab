#!/usr/bin/env python3
r"""Cross-platform install routine for MTG Deck Analyzer.

Creates the backend's virtual environment (if missing) and installs its
dependencies. Pure standard library, works the same on macOS/Linux/Windows
as long as a Python 3 interpreter is on PATH.

Usage:
  python3 setup/install.py      (macOS/Linux)
  python setup\install.py       (Windows)
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
VENV_DIR = BACKEND_DIR / "venv"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"


def venv_python(venv_dir: Path) -> Path:
    """Path to a venv's python executable, cross-platform."""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def activate_hint() -> str:
    if sys.platform == "win32":
        return str(VENV_DIR / "Scripts" / "activate.bat")
    return f"source {VENV_DIR / 'bin' / 'activate'}"


def ensure_backend_venv() -> Path:
    """Create the backend venv if missing and install its requirements.

    Returns the path to the venv's python executable.
    """
    if not VENV_DIR.exists():
        print(f"Creating virtual environment in {VENV_DIR} ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    python = venv_python(VENV_DIR)
    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)], check=True)
    return python


def main() -> None:
    ensure_backend_venv()
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
