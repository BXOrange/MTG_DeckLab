"""Security-event log (PLR-9e, plan section 7).

One line per event, `key=value` pairs, written to the logger ``decklab.security`` and, unless
disabled, to a rotating file (`config.SECURITY_LOG_FILE`, owner-only). It is separate from the
application log so it can be kept longer, reviewed and shipped on its own.

What is logged: authentication outcomes, authorization failures, session lifecycle, password
recovery, admin data access and privileged mutations (the latter also land in the `audit_log`
table and are mirrored here by `AccountStore.record_audit`).

What is never logged: passwords, session or CSRF tokens, cookies, invitation/recovery tokens, TOTP
secrets and codes, request bodies or private deck/asset contents. Field *names* that suggest a
secret are rejected outright (`FORBIDDEN_FIELD_PARTS`), and every value is stripped of control
characters and cut to `VALUE_MAX`, because names and paths are player-controlled (log injection).

Review and retention: see SERVER_GUIDE section 4c. The file rotates at `SECURITY_LOG_MAX_BYTES`
and keeps `SECURITY_LOG_BACKUPS` rotated files; nothing else deletes it.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import threading
import unicodedata
from pathlib import Path

from mtg_analyzer import config

#: Logger name of the security stream (separate from the application's `mtg_analyzer.*` loggers).
LOGGER_NAME = "decklab.security"

#: Longest value written to a log line; names, paths and targets are player-controlled.
VALUE_MAX = 120

#: A field whose name contains one of these is a programming error: a secret must not be logged.
FORBIDDEN_FIELD_PARTS = ("password", "token", "cookie", "csrf", "secret", "otp", "code", "authorization", "body")

#: Path segments that look like identifiers are collapsed so ids and tokens never reach the log.
_ID_SEGMENT = re.compile(r"^(?:[0-9a-fA-F-]{8,}|\d+)$")

_logger = logging.getLogger(LOGGER_NAME)
_configured = False
_configure_lock = threading.Lock()


class _PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating file whose every (re)opened file is owner-only, so rotation never widens access."""

    def _open(self):
        stream = super()._open()
        from mtg_analyzer.services import account_crypto

        account_crypto.restrict(self.baseFilename)
        return stream


def clean(value: object) -> str:
    """A log-safe, bounded, single-line rendering of a value."""
    text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(value))
    text = text.replace('"', "'")
    return text[:VALUE_MAX]


def route_of(path: str) -> str:
    """A request path with identifier-like segments replaced, so ids/tokens in URLs are not logged."""
    segments = ["{id}" if _ID_SEGMENT.match(part) else part for part in path.split("/")]
    return clean("/".join(segments))


def format_event(event: str, fields: dict[str, object]) -> str:
    parts = [f"event={clean(event)}"]
    for name, value in fields.items():
        lowered = name.lower()
        if any(part in lowered for part in FORBIDDEN_FIELD_PARTS):
            raise ValueError(f"security log field {name!r} may carry a secret")
        if value is None:
            continue
        parts.append(f'{name}="{clean(value)}"')
    return " ".join(parts)


def configure() -> None:
    """Attach the rotating, owner-only file handler once (idempotent). Safe without a data dir."""
    global _configured
    with _configure_lock:
        if _configured:
            return
        _configured = True
        _logger.setLevel(logging.INFO)
        _logger.propagate = False  # the security stream stays out of the application log
        if not _logger.handlers:
            _logger.addHandler(logging.StreamHandler())
        target = config.SECURITY_LOG_FILE.strip()
        if not target:
            return
        path = Path(target)
        try:
            from mtg_analyzer.services import account_crypto

            created_dir = not path.parent.exists()
            path.parent.mkdir(parents=True, exist_ok=True)
            if created_dir:
                account_crypto.restrict(path.parent, directory=True)
            path.touch(mode=account_crypto.PRIVATE_FILE_MODE, exist_ok=True)
            handler = _PrivateRotatingFileHandler(
                path, maxBytes=config.SECURITY_LOG_MAX_BYTES, backupCount=config.SECURITY_LOG_BACKUPS,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            _logger.addHandler(handler)
            account_crypto.restrict(path)
        except OSError:
            logging.getLogger(__name__).warning("security log file %s is not writable; logging to stderr only", path)


def event(name: str, /, **fields: object) -> None:
    """Record one security event, e.g. `event("auth.login", outcome="failure", source="10.0.0.5")`."""
    configure()
    _logger.info(format_event(name, fields))
