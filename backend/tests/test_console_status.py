"""Launcher diagnostics must use live presence and require the launch secret."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mtg_analyzer.api import console_status as status


def test_status_disabled_and_wrong_secret(monkeypatch):
    monkeypatch.delenv("MTG_CONSOLE_TOKEN", raising=False)
    with pytest.raises(HTTPException):
        asyncio.run(status.console_status(""))
    monkeypatch.setenv("MTG_CONSOLE_TOKEN", "secret")
    with pytest.raises(HTTPException):
        asyncio.run(status.console_status("wrong"))


def test_status_counts_only_connected_players(monkeypatch):
    monkeypatch.setenv("MTG_CONSOLE_TOKEN", "secret")
    lobby = SimpleNamespace(
        players=lambda: [SimpleNamespace(id="a", name="Alice"), SimpleNamespace(id="b", name="Bob")],
        games=lambda: [SimpleNamespace(id="g", name="Table", status="running")],
    )
    monkeypatch.setattr(status, "get_lobby", lambda: lobby)
    monkeypatch.setattr(status.lobby_connections, "is_connected", lambda pid: pid == "a")
    monkeypatch.setattr(status.game_connections, "_connections", {"solo": {object()}})
    result = asyncio.run(status.console_status("secret"))
    assert result["players"] == ["Alice"]
    assert result["games"] == [{"id": "g", "name": "Table", "status": "running"}]
    assert result["game_connections"] == 1
    assert result["threads"]
