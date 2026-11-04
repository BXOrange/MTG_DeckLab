"""PLR-19: `setup/start.py --admin-port` validation and the proxy-mode default."""
import argparse
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def launcher(monkeypatch):
    setup = Path(__file__).resolve().parents[2] / "setup"
    monkeypatch.syspath_prepend(str(setup))
    spec = importlib.util.spec_from_file_location("admin_port_launcher", setup / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse(launcher, argv):
    parser = argparse.ArgumentParser()
    for flag in ("lan", "online", "localdev", "behind_tls_proxy"):
        parser.add_argument("--" + flag.replace("_", "-"), action="store_true")
    parser.add_argument("--host", default=None)
    parser.add_argument("--allow-network", action="append", default=[])
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--admin-port", type=int, default=None)
    return launcher.resolve_run_mode(parser.parse_args(argv), parser)


PROXY = ["--online", "--behind-tls-proxy"]


def test_proxy_mode_defaults_to_the_backend_port_plus_one(launcher):
    assert _parse(launcher, PROXY)[2]["MTG_ADMIN_PORT"] == "8001"
    assert _parse(launcher, PROXY + ["--backend-port", "9000"])[2]["MTG_ADMIN_PORT"] == "9001"


def test_explicit_admin_port_is_exported(launcher):
    assert _parse(launcher, PROXY + ["--admin-port", "9555"])[2]["MTG_ADMIN_PORT"] == "9555"


def test_zero_disables_the_admin_listener(launcher):
    assert "MTG_ADMIN_PORT" not in _parse(launcher, PROXY + ["--admin-port", "0"])[2]


@pytest.mark.parametrize("argv", [
    ["--admin-port", "9555"],                                  # LAN default: not in proxy mode
    ["--localdev", "--admin-port", "9555"],
    ["--online", "--tls-cert", "c.pem", "--tls-key", "k.pem", "--admin-port", "9555"],  # TLS served directly
    PROXY + ["--admin-port", "70000"],                         # out of range
    PROXY + ["--admin-port", "-3"],
    PROXY + ["--admin-port", "8000"],                          # same as --backend-port
    PROXY + ["--admin-port", "8765"],                          # same as --port
])
def test_invalid_admin_port_combinations_exit(launcher, argv):
    with pytest.raises(SystemExit):
        _parse(launcher, argv)


def test_other_modes_export_no_admin_port(launcher):
    assert "MTG_ADMIN_PORT" not in _parse(launcher, [])[2]
