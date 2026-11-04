"""PLR-9d: the static /admin page is local-only, strictly sandboxed and renders only text."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_frontend_proxy_client
from mtg_analyzer.api.frontend_proxy import ADMIN_PAGE_CSP

ADMIN_DIR = Path(__file__).resolve().parents[3] / "frontend" / "admin"


class _Handler(BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):  # noqa: N802
        type(self).seen.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Cache-Control", "max-age=60")
        self.end_headers()
        self.wfile.write(b"<html>admin fixture</html>")

    def log_message(self, *_):
        pass


@pytest.fixture
def upstream():
    _Handler.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = httpx.Client(base_url=f"http://127.0.0.1:{server.server_address[1]}")
    app.dependency_overrides[get_frontend_proxy_client] = lambda: client
    yield _Handler
    app.dependency_overrides.pop(get_frontend_proxy_client, None)
    server.shutdown()


@pytest.mark.real_socket
@pytest.mark.parametrize("path", ["/admin", "/admin/", "/admin/admin.js", "/admin/index.html"])
def test_a_lan_client_gets_403_through_the_proxy_without_reaching_the_frontend(upstream, path):
    lan = TestClient(app, base_url="http://localhost", client=("192.168.1.20", 4000))
    assert lan.get(path).status_code == 403
    assert upstream.seen == []


@pytest.mark.real_socket
def test_forwarding_headers_and_foreign_host_are_not_local(upstream):
    local = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 4000))
    assert local.get("/admin", headers={"X-Forwarded-For": "10.0.0.5"}).status_code == 403
    assert local.get("/admin", headers={"Forwarded": "for=10.0.0.5"}).status_code == 403
    assert upstream.seen == []


@pytest.mark.real_socket
def test_local_client_gets_the_page_with_its_own_strict_csp(upstream):
    local = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 4000))
    r = local.get("/admin")
    assert r.status_code == 200 and upstream.seen == ["/admin/index.html"]
    assert r.headers["content-security-policy"] == ADMIN_PAGE_CSP
    assert r.headers["cache-control"] == "no-store"
    assert "unsafe-inline" not in ADMIN_PAGE_CSP and "script-src 'self'" in ADMIN_PAGE_CSP
    assert "http" not in ADMIN_PAGE_CSP  # no external source
    assert "connect-src 'self'" in ADMIN_PAGE_CSP and "form-action 'none'" in ADMIN_PAGE_CSP


@pytest.mark.real_socket
def test_the_ordinary_app_keeps_its_own_policy(upstream):
    local = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 4000))
    assert "unsafe-inline" in local.get("/index.html").headers["content-security-policy"]  # style-src of the app


def test_page_source_has_no_inline_script_handler_or_html_sink():
    html = (ADMIN_DIR / "index.html").read_text(encoding="utf-8")
    js = (ADMIN_DIR / "admin.js").read_text(encoding="utf-8")
    css = (ADMIN_DIR / "admin.css").read_text(encoding="utf-8")
    assert "<script>" not in html and " onclick" not in html and "style=" not in html
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in js, sink
    for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
        assert storage not in js, storage  # the password lives in memory only
    assert "credentials: 'omit'" in js
    assert "@import" not in css and "url(" not in css
