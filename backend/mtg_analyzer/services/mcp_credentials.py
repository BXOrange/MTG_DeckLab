"""Persistent MCP connection credential, kept out of the repository."""
import hmac
import os
import secrets
import tempfile
import threading

from mtg_analyzer import config

_lock = threading.RLock()


def _path():
    return config.DATA_DIR / 'mcp_server_token'


def read_token():
    try:
        return _path().read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return ''


def rotate_token():
    token = secrets.token_urlsafe(32)
    with _lock:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.mcp-token-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                out.write(token)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    return token


def matches(token):
    saved = read_token()
    return bool(saved and token and hmac.compare_digest(saved, token))
