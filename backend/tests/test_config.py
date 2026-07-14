"""Tests for the central on-disk-path/config module.

Reference: backend/ToDo_Backend.md "Configuration".

`mtg_analyzer.config` reads its values from environment variables at
import time, so exercising an override means running a fresh
interpreter with the env var set rather than reloading the already-
imported module in-process (other test modules may have imported it
first with different environment state).
"""

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run(code: str, env_overrides: dict) -> str:
    import os

    env = dict(os.environ, **env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_REPO_ROOT / "backend"),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class TestDefaults:
    def test_cache_and_data_dirs_default_repo_relative(self):
        out = _run(
            "from mtg_analyzer import config; "
            "print(config.CACHE_DIR); print(config.DATA_DIR)",
            env_overrides={},
        )
        cache_dir, data_dir = out.splitlines()
        assert Path(cache_dir) == _REPO_ROOT / "backend" / "cache"
        assert Path(data_dir) == _REPO_ROOT / "backend" / "data"

    def test_user_agent_and_rate_limit_defaults(self):
        out = _run(
            "from mtg_analyzer import config; "
            "print(config.USER_AGENT); print(config.SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS)",
            env_overrides={},
        )
        user_agent, interval = out.splitlines()
        assert user_agent == "MTG-Deck-Analyzer/0.1"
        assert float(interval) == 0.1

    def test_scryfall_primary_defaults_false(self):
        out = _run(
            "from mtg_analyzer import config; print(config.SCRYFALL_PRIMARY)",
            env_overrides={},
        )
        assert out == "False"


class TestEnvOverrides:
    def test_mtg_cache_dir_override(self, tmp_path):
        out = _run(
            "from mtg_analyzer import config; print(config.CACHE_DIR); print(config.DB_PATH); print(config.IMAGE_CACHE_DIR)",
            env_overrides={"MTG_CACHE_DIR": str(tmp_path)},
        )
        cache_dir, db_path, image_dir = out.splitlines()
        assert Path(cache_dir) == tmp_path
        assert Path(db_path) == tmp_path / "db" / "cards.db"
        assert Path(image_dir) == tmp_path / "images"

    def test_mtg_data_dir_override(self, tmp_path):
        out = _run(
            "from mtg_analyzer import config; print(config.DATA_DIR); print(config.DECKS_DB_PATH); print(config.PLAYER_ASSETS_DB_PATH)",
            env_overrides={"MTG_DATA_DIR": str(tmp_path)},
        )
        data_dir, decks_path, assets_path = out.splitlines()
        assert Path(data_dir) == tmp_path
        assert Path(decks_path) == tmp_path / "decks.db"
        assert Path(assets_path) == tmp_path / "player_assets.db"

    def test_mtg_user_agent_and_rate_limit_override(self):
        out = _run(
            "from mtg_analyzer import config; "
            "print(config.USER_AGENT); print(config.SCRYFALL_MIN_REQUEST_INTERVAL_SECONDS)",
            env_overrides={
                "MTG_USER_AGENT": "Test-Agent/1.0",
                "MTG_SCRYFALL_MIN_REQUEST_INTERVAL": "0.25",
            },
        )
        user_agent, interval = out.splitlines()
        assert user_agent == "Test-Agent/1.0"
        assert float(interval) == 0.25

    def test_mtg_scryfall_primary_override(self):
        out = _run(
            "from mtg_analyzer import config; print(config.SCRYFALL_PRIMARY)",
            env_overrides={"MTG_SCRYFALL_PRIMARY": "1"},
        )
        assert out == "True"

    def test_mtg_scryfall_primary_accepts_true_and_yes(self):
        for value in ("true", "TRUE", "yes"):
            out = _run(
                "from mtg_analyzer import config; print(config.SCRYFALL_PRIMARY)",
                env_overrides={"MTG_SCRYFALL_PRIMARY": value},
            )
            assert out == "True", f"expected True for {value!r}"

    def test_mtg_scryfall_primary_rejects_unrecognized_value(self):
        out = _run(
            "from mtg_analyzer import config; print(config.SCRYFALL_PRIMARY)",
            env_overrides={"MTG_SCRYFALL_PRIMARY": "0"},
        )
        assert out == "False"

    def test_overrides_flow_through_service_modules(self, tmp_path):
        cache_dir = tmp_path / "cache"
        data_dir = tmp_path / "data"
        out = _run(
            "from mtg_analyzer.services.card_database import DEFAULT_DB_PATH; "
            "from mtg_analyzer.services.deck_database import DEFAULT_DECKS_DB_PATH; "
            "from mtg_analyzer.services.image_cache import DEFAULT_IMAGE_CACHE_DIR; "
            "from mtg_analyzer.services.player_assets import DEFAULT_PLAYER_ASSETS_DB_PATH; "
            "print(DEFAULT_DB_PATH); print(DEFAULT_DECKS_DB_PATH); "
            "print(DEFAULT_IMAGE_CACHE_DIR); print(DEFAULT_PLAYER_ASSETS_DB_PATH)",
            env_overrides={"MTG_CACHE_DIR": str(cache_dir), "MTG_DATA_DIR": str(data_dir)},
        )
        db_path, decks_path, image_dir, assets_path = out.splitlines()
        assert Path(db_path) == cache_dir / "db" / "cards.db"
        assert Path(decks_path) == data_dir / "decks.db"
        assert Path(image_dir) == cache_dir / "images"
        assert Path(assets_path) == data_dir / "player_assets.db"
