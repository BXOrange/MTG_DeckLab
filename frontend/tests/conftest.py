"""Shared setup for the browser tests.

Every test serves `frontend/` from a stdlib `ThreadingHTTPServer` and loads the
board as ES modules, so Chromium opens dozens of connections at once while it
resolves the import graph. The stdlib default listen backlog (5) is smaller
than that burst, so some connections were refused and the page failed with
"Failed to fetch dynamically imported module" at random. A larger backlog makes
the module graph load reliably as it grows.
"""
import socketserver

# Comfortably above the number of modules the board imports; the OS caps it anyway.
TEST_SERVER_BACKLOG = 128

socketserver.TCPServer.request_queue_size = TEST_SERVER_BACKLOG
