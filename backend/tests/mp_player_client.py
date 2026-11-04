"""Test client that signs multiplayer requests in as the right fake account.

PLR-9c: every multiplayer route needs the session account that owns the named lobby
player. Most tests only care about game behaviour and name players the way they always
did (``{"name": "Ann"}`` on connect, ``playerId`` afterwards), so this client picks the
fake account (`tests/support/auth.py`) from that: the connect body's ``name`` for
``POST /connect``, otherwise the account that owns the request's ``playerId`` /
``player_id``. A test that passes an ``X-Test-Account`` header itself (an empty string
means "no override" = the default test account) exercises the failure paths.
"""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from tests.support.auth import ACCOUNT_HEADER, account_header


class PlayerClient(TestClient):
    def __init__(self, *args, lobby, **kwargs):
        super().__init__(*args, **kwargs)
        self._account_lobby = lobby

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if ACCOUNT_HEADER not in headers:
            body = kwargs.get("json")
            player_id = None
            if isinstance(body, dict):
                player_id = body.get("playerId") or body.get("player_id")
            if player_id is None:
                query = parse_qs(urlparse(str(url)).query)
                player_id = (query.get("player_id") or [None])[0]
            if player_id is None:
                player_id = (kwargs.get("params") or {}).get("player_id")
            player = self._account_lobby.find(player_id) if player_id else None
            if player is not None and player.player_uuid:
                headers.update(account_header(player.name, player.player_uuid))
            elif str(url).endswith("/api/multiplayer/connect") and isinstance(body, dict) and body.get("name"):
                headers.update(account_header(body["name"]))
        elif headers[ACCOUNT_HEADER] == "":
            del headers[ACCOUNT_HEADER]
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
