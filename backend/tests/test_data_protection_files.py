"""PLR-9e: the data directory, key material and logs are never served, exported or versioned."""

import subprocess
from pathlib import Path

import pytest

from mtg_analyzer import config

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", [
    "backend/data/accounts.db", "backend/data/accounts.db-wal", "anywhere/accounts.key",
    "anywhere/accounts.key.previous-20260101T000000Z", "x/backups/accounts-20260101T000000Z.db",
    "backend/data/logs/security.log", "elsewhere/security.log.1",
])
def test_sensitive_files_are_git_ignored(name):
    result = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO)
    assert result.returncode == 0, f"{name} is not git-ignored"


def test_static_roots_do_not_contain_the_data_dir():
    """The frontend server serves `frontend/` (and `user-docs/`); the data dir lies in neither."""
    for root in (REPO / "frontend", REPO / "user-docs"):
        assert not config.DATA_DIR.resolve().is_relative_to(root.resolve())


def test_no_static_mount_and_only_the_image_cache_is_served_from_disk():
    """No `StaticFiles` mount exists, and the one `FileResponse` (cached card images) reads the cache dir, never the data dir."""
    api = REPO / "backend" / "mtg_analyzer" / "api"
    users = []
    for path in api.glob("*.py"):
        text = path.read_text()
        assert "StaticFiles" not in text, path.name
        if "FileResponse(" in text:
            users.append(path.name)
    assert users == ["images.py"]
    assert "DATA_DIR" not in (api / "images.py").read_text()


def test_bug_report_dir_is_outside_the_data_dir():
    assert not config.BUG_REPORT_DIR.resolve().is_relative_to(config.DATA_DIR.resolve())
