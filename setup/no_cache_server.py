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

DEFAULT_PORT = 8000


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    ThreadingHTTPServer(("", port), NoCacheHandler).serve_forever()


if __name__ == "__main__":
    main()
