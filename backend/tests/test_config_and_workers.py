"""Config-file loading (`env var > config.json > default`) and the
worker/concurrency knobs it feeds: the server request-thread pool
(`api/app.py`) and the dynamic-analysis per-job process pool
(`services/dynamic_analysis.py`).
"""

from __future__ import annotations

import importlib
import json

import anyio
import pytest

from mtg_analyzer.services.dynamic_analysis import (
    _MIN_MATCHES_FOR_PROCESS_POOL,
    _match_worker_count,
    run_dynamic_analysis,
)
from tests.test_dynamic_analysis import _cheap_creature, _commander, _forest


def _reload_config(monkeypatch, *, config_file=None, env=None):
    """Re-import mtg_analyzer.config with a chosen config file / env so the
    module-level constants are recomputed from scratch."""
    for key in list(env or {}):
        monkeypatch.setenv(key, str(env[key]))
    if config_file is not None:
        monkeypatch.setenv("MTG_CONFIG_FILE", str(config_file))
    import mtg_analyzer.config as config

    return importlib.reload(config)


class TestConfigFile:
    def test_missing_file_falls_back_to_defaults(self, monkeypatch, tmp_path):
        cfg = _reload_config(monkeypatch, config_file=tmp_path / "does-not-exist.json")
        assert cfg.SERVER_THREAD_WORKERS == 40
        assert cfg.DYNAMIC_ANALYSIS_WORKERS == 4
        assert cfg.DYNAMIC_ANALYSIS_MATCH_WORKERS == 0
        assert cfg.LOG_LEVEL == "WARNING"
        assert cfg.USER_AGENT == "MTG-Deck-Analyzer/0.1"

    def test_log_level_is_uppercased_from_file_and_env(self, monkeypatch, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"logging": {"level": "info"}}))
        assert _reload_config(monkeypatch, config_file=path).LOG_LEVEL == "INFO"
        assert _reload_config(
            monkeypatch, config_file=path, env={"MTG_LOG_LEVEL": "debug"}
        ).LOG_LEVEL == "DEBUG"

    def test_file_values_override_defaults(self, monkeypatch, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({
            "workers": {"server_threads": 8, "dynamic_analysis_match_processes": 3},
            "scryfall": {"user_agent": "custom/9", "primary": True},
        }))
        cfg = _reload_config(monkeypatch, config_file=path)
        assert cfg.SERVER_THREAD_WORKERS == 8
        assert cfg.DYNAMIC_ANALYSIS_MATCH_WORKERS == 3
        assert cfg.USER_AGENT == "custom/9"
        assert cfg.SCRYFALL_PRIMARY is True

    def test_env_var_beats_the_file(self, monkeypatch, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"workers": {"server_threads": 8}}))
        cfg = _reload_config(monkeypatch, config_file=path, env={"MTG_SERVER_THREAD_WORKERS": 99})
        assert cfg.SERVER_THREAD_WORKERS == 99

    def test_empty_string_in_file_means_use_default(self, monkeypatch, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"paths": {"cache_dir": ""}, "scryfall": {"user_agent": ""}}))
        cfg = _reload_config(monkeypatch, config_file=path)
        assert cfg.USER_AGENT == "MTG-Deck-Analyzer/0.1"
        assert cfg.CACHE_DIR.name == "cache"

    def test_malformed_file_is_ignored_with_a_warning(self, monkeypatch, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ not json")
        with pytest.warns(RuntimeWarning):
            cfg = _reload_config(monkeypatch, config_file=path)
        assert cfg.SERVER_THREAD_WORKERS == 40

    def test_shipped_config_json_parses_and_is_the_source_of_truth(self, monkeypatch):
        """The committed config.json must parse and actually feed config.py
        (whatever values it currently holds — it's meant to be edited)."""
        for var in ("MTG_SERVER_THREAD_WORKERS", "MTG_DYNAMIC_ANALYSIS_WORKERS",
                    "MTG_DYNAMIC_ANALYSIS_MATCH_WORKERS", "MTG_LOG_LEVEL", "MTG_USER_AGENT"):
            monkeypatch.delenv(var, raising=False)
        cfg = _reload_config(monkeypatch)  # no MTG_CONFIG_FILE override -> the real file
        data = json.loads(cfg.CONFIG_FILE.read_text())
        assert set(data) >= {"logging", "scryfall", "multiplayer", "workers", "paths"}
        assert cfg.SERVER_THREAD_WORKERS == data["workers"]["server_threads"]
        assert cfg.DYNAMIC_ANALYSIS_WORKERS == data["workers"]["dynamic_analysis_workers"]
        assert cfg.DYNAMIC_ANALYSIS_MATCH_WORKERS == data["workers"]["dynamic_analysis_match_processes"]
        assert cfg.LOG_LEVEL == data["logging"]["level"].upper()
        assert cfg.USER_AGENT == data["scryfall"]["user_agent"]


class TestLoggingSetup:
    @pytest.fixture(autouse=True)
    def _restore_app_logger_level(self):
        import logging

        saved = logging.getLogger("mtg_analyzer").level
        yield
        logging.getLogger("mtg_analyzer").setLevel(saved)

    def _configure_with(self, monkeypatch, level):
        import mtg_analyzer.config as config

        app_module = importlib.import_module("mtg_analyzer.api.app")
        monkeypatch.setattr(config, "LOG_LEVEL", level)
        app_module._configure_logging()
        import logging

        return logging.getLogger("mtg_analyzer").getEffectiveLevel()

    def test_default_is_warning(self, monkeypatch):
        import logging

        assert self._configure_with(monkeypatch, "WARNING") == logging.WARNING

    def test_info_lowers_only_the_app_logger_not_root(self, monkeypatch):
        import logging

        assert self._configure_with(monkeypatch, "INFO") == logging.INFO
        # Root stays quiet so third-party libraries aren't unmuted.
        assert logging.getLogger().getEffectiveLevel() == logging.WARNING

    def test_uvicorn_trace_level_maps_to_debug(self, monkeypatch):
        import logging

        assert self._configure_with(monkeypatch, "TRACE") == logging.DEBUG

    def test_unknown_level_falls_back_to_warning(self, monkeypatch):
        import logging

        assert self._configure_with(monkeypatch, "BOGUS") == logging.WARNING


class TestMatchWorkerCount:
    def test_zero_config_means_one_per_cpu_core(self, monkeypatch):
        import mtg_analyzer.config as config
        import os

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 0)
        big = 10_000
        assert _match_worker_count(big) == (os.cpu_count() or 1)

    def test_one_config_disables_the_pool(self, monkeypatch):
        import mtg_analyzer.config as config

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 1)
        assert _match_worker_count(50) == 1

    def test_small_jobs_never_use_the_pool(self, monkeypatch):
        import mtg_analyzer.config as config

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 8)
        assert _match_worker_count(_MIN_MATCHES_FOR_PROCESS_POOL - 1) == 1

    def test_capped_at_the_match_count(self, monkeypatch):
        import mtg_analyzer.config as config

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 64)
        assert _match_worker_count(5) == 5


def _mixed_library():
    return [_forest() for _ in range(40)] + [_cheap_creature() for _ in range(20)]


class TestDynamicAnalysisParallelism:
    def test_process_pool_and_in_process_agree_on_shape(self, monkeypatch):
        """A pooled run and a forced in-process run of the same size must
        produce the same result structure and match count."""
        import mtg_analyzer.config as config

        lib = _mixed_library()
        kwargs = dict(bot_kind="goldfish", num_matches=6, max_turns=3)

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 1)
        serial = run_dynamic_analysis(lib, [_commander()], **kwargs)

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 2)
        parallel = run_dynamic_analysis(lib, [_commander()], **kwargs)

        assert serial.matches_run == parallel.matches_run == 6
        assert [row["turn"] for row in serial.per_turn] == [row["turn"] for row in parallel.per_turn]
        assert serial.to_dict().keys() == parallel.to_dict().keys()

    def test_progress_callback_fires_once_per_match_under_the_pool(self, monkeypatch):
        import mtg_analyzer.config as config

        monkeypatch.setattr(config, "DYNAMIC_ANALYSIS_MATCH_WORKERS", 2)
        seen = []
        run_dynamic_analysis(
            _mixed_library(), [_commander()],
            bot_kind="goldfish", num_matches=5, max_turns=2,
            on_progress=lambda done, total: seen.append((done, total)),
        )
        assert [d for d, _ in seen] == [1, 2, 3, 4, 5]
        assert all(total == 5 for _, total in seen)


class TestServerThreadWorkers:
    def test_lifespan_hook_resizes_the_anyio_thread_pool(self, monkeypatch):
        # NB: `mtg_analyzer.api.__init__` does `from .app import app`, so the
        # name `mtg_analyzer.api.app` resolves to the FastAPI instance, not
        # the module — import the module explicitly.
        app_module = importlib.import_module("mtg_analyzer.api.app")
        import mtg_analyzer.config as config

        monkeypatch.setattr(config, "SERVER_THREAD_WORKERS", 123)

        async def _check():
            app_module._apply_server_thread_workers()
            return anyio.to_thread.current_default_thread_limiter().total_tokens

        assert anyio.run(_check) == 123
