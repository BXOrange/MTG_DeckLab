"""PLR-9a: `setup/start.py` run-mode flag validation (`resolve_run_mode`)."""
import argparse
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def launcher(monkeypatch):
    setup = Path(__file__).resolve().parents[2] / "setup"
    monkeypatch.syspath_prepend(str(setup))
    spec = importlib.util.spec_from_file_location("run_mode_launcher", setup / "start.py")
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
    return launcher.resolve_run_mode(parser.parse_args(argv), parser)


def test_no_flag_keeps_legacy_behaviour(launcher):
    assert _parse(launcher, []) == (None, None, {})


def test_lan_binds_all_interfaces_and_exports_networks(launcher):
    mode, host, env = _parse(launcher, ["--lan", "--allow-network", "192.168.179.0/24", "--allow-network", "10.0.0.0/8"])
    assert (mode, host) == ("lan", "0.0.0.0")
    assert env == {"MTG_RUN_MODE": "lan", "MTG_ALLOWED_NETWORKS": "192.168.179.0/24,10.0.0.0/8"}


def test_localdev_stays_on_loopback(launcher):
    assert _parse(launcher, ["--localdev"]) == ("localdev", None, {"MTG_RUN_MODE": "localdev"})


@pytest.mark.parametrize("argv", [
    ["--lan", "--online", "--behind-tls-proxy"],      # exclusive modes
    ["--lan", "--allow-network", "not-a-cidr"],       # invalid CIDR is a startup error
    ["--localdev", "--allow-network", "10.0.0.0/8"],  # allowlist only applies to LAN
    ["--localdev", "--host", "0.0.0.0"],              # localdev refuses non-loopback binds
    ["--online"],                                     # online without TLS
    ["--online", "--tls-cert", "c.pem"],              # cert without key
    ["--lan", "--behind-tls-proxy"],                  # TLS flags are online-only
])
def test_invalid_combinations_exit(launcher, argv):
    with pytest.raises(SystemExit):
        _parse(launcher, argv)


def test_online_with_tls_files_or_proxy(launcher):
    mode, host, env = _parse(launcher, ["--online", "--tls-cert", "c.pem", "--tls-key", "k.pem"])
    assert mode == "online" and host == "0.0.0.0"
    assert env["MTG_TLS_CERT"] == "c.pem" and env["MTG_TLS_KEY"] == "k.pem"
    assert _parse(launcher, ["--online", "--behind-tls-proxy"])[0] == "online"
    # PLR-9d: only a declared proxy lets the backend trust X-Forwarded-Proto for remote /admin.
    assert "MTG_BEHIND_TLS_PROXY" not in env
    assert _parse(launcher, ["--online", "--behind-tls-proxy"])[2]["MTG_BEHIND_TLS_PROXY"] == "1"
