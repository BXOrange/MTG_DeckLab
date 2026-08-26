"""Tests for `setup/install.py`'s offline-startup guarantee.

`setup/start.py` calls `ensure_backend_venv()` on *every* start, so these
are effectively tests of "can the app be started without an internet
connection". The contract they pin down:

* an already-populated venv is verified with `pip --no-index` only, so no
  socket is opened at all (the probe that would open one is monkeypatched
  to fail loudly here);
* a genuinely missing dependency with no network produces an actionable
  error naming the wheelhouse, rather than pip's tens-of-seconds retry
  stall followed by a raw traceback.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_INSTALL_PY = Path(__file__).resolve().parents[2] / "setup" / "install.py"


def _load_install_module():
    """Import setup/install.py by path (it isn't part of any package)."""
    spec = importlib.util.spec_from_file_location("mtg_setup_install", _INSTALL_PY)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def install(monkeypatch, tmp_path):
    """The install module with its venv pointed at an existing tmp dir."""
    module = _load_install_module()
    venv_dir = tmp_path / "venv"
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "Scripts").mkdir(parents=True)
    monkeypatch.setattr(module, "VENV_DIR", venv_dir)
    monkeypatch.setattr(module, "WHEELHOUSE", tmp_path / "wheels")
    return module


class _RunRecorder:
    """Stand-in for `subprocess.run` recording commands and faking exit codes."""

    def __init__(self, returncode: int = 0) -> None:
        self.commands: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, command, **kwargs):
        self.commands.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, self.returncode)


def test_populated_venv_installs_offline_and_opens_no_socket(install, monkeypatch):
    runs = _RunRecorder(returncode=0)
    monkeypatch.setattr(install.subprocess, "run", runs)
    # Any reachability probe would be a network call on the happy path.
    monkeypatch.setattr(
        install, "network_available", lambda *a, **k: pytest.fail("probed the network")
    )

    install.ensure_backend_venv()

    assert len(runs.commands) == 1, runs.commands
    assert "--no-index" in runs.commands[0]
    assert "--disable-pip-version-check" in runs.commands[0]


def test_no_unconditional_pip_self_upgrade(install, monkeypatch):
    """`pip install --upgrade pip` always queries PyPI — it must not run here."""
    runs = _RunRecorder(returncode=0)
    monkeypatch.setattr(install.subprocess, "run", runs)
    monkeypatch.setattr(install, "network_available", lambda *a, **k: True)

    install.ensure_backend_venv()

    assert not any("--upgrade" in command for command in runs.commands)


def test_missing_dependency_offline_points_at_the_wheelhouse(install, monkeypatch):
    monkeypatch.setattr(install.subprocess, "run", _RunRecorder(returncode=1))
    monkeypatch.setattr(install, "network_available", lambda *a, **k: False)

    with pytest.raises(RuntimeError) as excinfo:
        install.ensure_backend_venv()

    assert "--download-wheels" in str(excinfo.value)


def test_missing_dependency_online_retries_against_the_index(install, monkeypatch):
    class _FailOfflineOnly(_RunRecorder):
        def __call__(self, command, **kwargs):
            result = super().__call__(command, **kwargs)
            failed = "--no-index" in self.commands[-1]
            return subprocess.CompletedProcess(command, 1 if failed else 0)

    runs = _FailOfflineOnly()
    monkeypatch.setattr(install.subprocess, "run", runs)
    monkeypatch.setattr(install, "network_available", lambda *a, **k: True)

    install.ensure_backend_venv()

    assert "--no-index" in runs.commands[0]
    assert "--no-index" not in runs.commands[-1]


def test_wheelhouse_is_used_only_when_it_holds_wheels(install, tmp_path):
    wheelhouse = tmp_path / "wheels"
    assert install.wheelhouse_args(wheelhouse) == []

    wheelhouse.mkdir()
    assert install.wheelhouse_args(wheelhouse) == []

    (wheelhouse / "fastapi-0.115.0-py3-none-any.whl").write_bytes(b"")
    assert install.wheelhouse_args(wheelhouse) == ["--find-links", str(wheelhouse)]
