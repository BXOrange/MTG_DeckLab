"""Stdlib HTTP client for the token API (`mtg_analyzer/api/mcp_seat.py`).

No engine imports: the adapter sees exactly what any remote client sees.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

#: Headroom above the server's long-poll cap (`api/mcp_seat.MCP_WAIT_MAX_SECONDS`)
#: so the socket does not time out before the server answers a `wait`.
HTTP_TIMEOUT_SECONDS = 40.0


class SeatError(Exception):
    """The server refused a call; the message is meant for the model to read."""


def action_payload(offer: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate a legal attack offer to the shared game's declaration request."""
    action = {**offer, **(params or {})}
    if action.get('type') != 'attack':
        return action
    defenders = action.get('legal_defenders') or []
    if 'defender' not in action and defenders:
        if len(defenders) != 1:
            raise SeatError('Choose a legal_defenders entry in params.defender before attacking.')
        defender = defenders[0]
        action['defender'] = ({'kind': defender['kind'], 'instance_id': defender['instance_id']}
                              if 'instance_id' in defender else {'kind': 'player', 'id': defender['id']})
    action['type'] = 'declare_attackers'
    action.setdefault('instance_ids', [action['instance_id']])
    return action


class SeatClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base = base_url.rstrip("/")
        self._token = token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self._base}/api/mcp-seat{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get("detail", exc.reason)
            except (ValueError, AttributeError):
                detail = exc.reason
            raise SeatError(f"{exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SeatError(f"server not reachable: {exc.reason}") from exc

    def view(self) -> dict[str, Any]:
        return self._call("GET", "/view")

    def wait(self, timeout: float) -> dict[str, Any]:
        return self._call("GET", f"/wait?timeout={timeout}")

    def set_name(self, name: str) -> dict[str, Any]:
        return self._call("POST", "/name", {"name": name})

    def deck(self) -> dict[str, Any]:
        return self._call("GET", "/deck")

    def action(self, action: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/action", {"action": action})

    def concede(self) -> dict[str, Any]:
        return self._call("POST", "/concede", {})
