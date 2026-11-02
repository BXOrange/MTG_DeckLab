"""Test client that authenticates multiplayer requests like the real frontend.

BUG-39: every multiplayer route needs the caller's ``X-Player-Secret``.
Most tests only care about game behaviour, so this client looks the secret
up in the test's own `Lobby` from the ``playerId`` in the JSON body (or the
``player_id`` query parameter) and adds the header -- unless the test
passes an ``X-Player-Secret`` header itself (an empty string means "send
none"), which is how the authentication tests exercise the failure paths.
"""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from mtg_analyzer.api.multiplayer import PLAYER_SECRET_HEADER


class SecretInjectingClient(TestClient):
    def __init__(self, *args, lobby, **kwargs):
        super().__init__(*args, **kwargs)
        self._secret_lobby = lobby

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if PLAYER_SECRET_HEADER not in headers:
            player_id = None
            body = kwargs.get("json")
            if isinstance(body, dict):
                player_id = body.get("playerId") or body.get("player_id")
            if player_id is None:
                query = parse_qs(urlparse(str(url)).query)
                player_id = (query.get("player_id") or [None])[0]
            if player_id is None:
                player_id = (kwargs.get("params") or {}).get("player_id")
            player = self._secret_lobby.find(player_id) if player_id else None
            if player is not None:
                headers[PLAYER_SECRET_HEADER] = player.secret
        elif headers[PLAYER_SECRET_HEADER] == "":
            del headers[PLAYER_SECRET_HEADER]
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
