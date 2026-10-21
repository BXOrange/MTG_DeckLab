"""Console commands stop/restart supervision; EOF never stops servers."""
import importlib.util
from pathlib import Path
import queue
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(monkeypatch):
    setup = Path(__file__).resolve().parents[2] / "setup"
    monkeypatch.syspath_prepend(str(setup))
    spec = importlib.util.spec_from_file_location("console_launcher", setup / "start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", ["c", "r"])
def test_exit_commands(launcher, command):
    launcher._COMMANDS.put(command)
    assert launcher.supervise([SimpleNamespace(poll=lambda: None)], 8000) == command


def test_info_then_threads_then_stop(launcher, monkeypatch):
    seen = []
    monkeypatch.setattr(launcher, "print_server_status", lambda cmd, port: seen.append((cmd, port)))
    for cmd in ["i", "t", "c"]:
        launcher._COMMANDS.put(cmd)
    launcher.supervise([SimpleNamespace(poll=lambda: None)], 8000)
    assert seen == [("i", 8000), ("t", 8000)]


def test_eof_does_not_enqueue_shutdown(launcher, monkeypatch):
    monkeypatch.setattr(sys, "stdin", iter([]))
    launcher.read_console()
    with pytest.raises(queue.Empty):
        launcher._COMMANDS.get_nowait()


def test_child_exit_ends_supervision(launcher):
    assert launcher.supervise([SimpleNamespace(poll=lambda: 1)], 8000) == "c"


def test_restart_keeps_options_and_stops_each_process(launcher, monkeypatch):
    calls, stopped = [], []
    monkeypatch.setattr(sys, "argv", ["start.py", "--backend-only", "--no-browser", "--backend-port", "8123"])
    monkeypatch.setattr(launcher, "ensure_backend_venv", lambda: "python")
    monkeypatch.setattr(launcher.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(launcher.signal, "signal", lambda *args: None)
    monkeypatch.setattr(launcher, "_stop", stopped.append)

    def start(*args, **kwargs):
        proc = SimpleNamespace(poll=lambda: None)
        calls.append((args, kwargs, proc))
        return proc

    monkeypatch.setattr(launcher, "start_backend", start)
    launcher._COMMANDS.put("r")
    launcher._COMMANDS.put("c")
    launcher.main()
    assert len(calls) == 2
    assert calls[0][:2] == calls[1][:2]
    assert calls[0][0] == ("python", 8123)
    assert stopped == [call[2] for call in calls]
