"""Security-event middleware (PLR-9e, plan section 7): authorization failures and admin access.

Pure ASGI, like the other guards. It records, through `services/security_log.py`:

* every refusal (401, 403, 429) of an `/api/` call, with method, normalized route, status and source;
* every request to `/api/admin` (admin data access and privileged mutations), with the acting admin's
  `player_uuid` when `require_admin` identified one (`scope["state"]["actor"]`).

Only the route (identifier-like segments collapsed), the method, the status and the peer address are
read. Never headers, cookies, query strings or bodies, so no credential can reach the log.
"""

from __future__ import annotations

from mtg_analyzer.services import security_log

API_PREFIX = "/api/"
ADMIN_PREFIX = "/api/admin"
REFUSAL_STATUSES = frozenset({401, 403, 429})
#: Polled constantly by the page; its 401s for a logged-out visitor would only be noise.
QUIET_PATHS = frozenset({"/api/auth/me", "/api/health", "/api/console-status"})


class SecurityEventMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(API_PREFIX) or path in QUIET_PATHS:
            await self.app(scope, receive, send)
            return
        is_admin = path.startswith(ADMIN_PREFIX)

        async def send_logged(message) -> None:
            if message["type"] == "http.response.start":
                status = message["status"]
                if is_admin or status in REFUSAL_STATUSES:
                    client = scope.get("client")
                    state = scope.get("state") or {}
                    security_log.event(
                        "admin.request" if is_admin else "authz.refused",
                        method=scope.get("method"), route=security_log.route_of(path), status=status,
                        source=client[0] if client else None, actor=state.get("actor"),
                    )
            await send(message)

        await self.app(scope, receive, send_logged)
