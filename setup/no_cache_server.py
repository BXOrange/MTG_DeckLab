#!/usr/bin/env python3
"""Static file server for local frontend dev — identical to
`python -m http.server` except every response also gets
`Cache-Control: no-store`.

Plain `http.server` sends no Cache-Control/Expires header at all, only
Last-Modified. Per RFC 7234 4.2.2, when a server gives no explicit
freshness info browsers apply *heuristic* freshness and may serve a
page from their own disk cache on a normal reload without ever asking
the server — so edited frontend files silently don't show up until a
hard refresh. `no-store` forces every request to hit this server.

Usage: python3 no_cache_server.py [port]  (serves the current directory)
Used by setup/start.py instead of `python -m http.server`.
"""

import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

DEFAULT_PORT = 8000
USER_DOCS_DIR = Path(__file__).resolve().parent.parent / "user-docs"


class NoCacheHandler(SimpleHTTPRequestHandler):
    def log_request(self, code="-", size="-") -> None:
        # Keep the launcher console available for commands. HTTP errors
        # still go through SimpleHTTPRequestHandler.log_error().
        pass

    def translate_path(self, path: str) -> str:
        """Expose the player guide without copying it into the frontend tree.

        The normal document root remains the frontend directory. Only the
        explicit /user-docs/ prefix may resolve outside it, and the resolved
        path is kept beneath USER_DOCS_DIR to reject traversal attempts.
        """
        request_path = unquote(urlsplit(path).path)
        if request_path.startswith("/user-docs/"):
            relative = request_path.removeprefix("/user-docs/")
            candidate = (USER_DOCS_DIR / relative).resolve()
            if candidate.is_relative_to(USER_DOCS_DIR):
                return str(candidate)
        return super().translate_path(path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    # Loopback-only, not "" (all interfaces): binding every interface makes
    # macOS treat this as wanting LAN-wide incoming connections, which
    # requires the "Local Network" privacy permission. That prompt is
    # unreliable for a bare CLI script (no signed app bundle) — it can fail
    # to surface at all, leaving the port silently unreachable until
    # something resets the permission broker's pending state (a reboot).
    # This is a local dev server; it only needs to answer 127.0.0.1 anyway,
    # same as the backend's uvicorn (host-less --port also defaults to
    # loopback), which is why the backend never hit this.
    try:
        with ThreadingHTTPServer(("127.0.0.1", port), NoCacheHandler) as server:
            server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl+C reaches the launcher and its children together.
        # Treat it as a normal stop and let the context close the socket.
        pass


if __name__ == "__main__":
    main()
