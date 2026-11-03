"""Password acceptance rules and the advisory strength meter (PLR-9a, plan §3).

The server enforces only the minimum length, the maximum length and the
compromised-password blocklist (the "red" class). Digits and special characters
are *recommendations*: they move a valid password from yellow to green but are
never required (no composition rules, OWASP). The frontend mirrors `strength`
locally for the red/yellow/green meter; the blocklist is server-side only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from mtg_analyzer import config

_BLOCKLIST_PATH = Path(__file__).resolve().parent.parent / "data" / "common_passwords.txt"


@lru_cache(maxsize=1)
def _blocklist() -> frozenset[str]:
    try:
        lines = _BLOCKLIST_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(line.strip().lower() for line in lines if line.strip())


def min_length(admin: bool) -> int:
    return config.ADMIN_PASSWORD_MIN_LENGTH if admin else config.PASSWORD_MIN_LENGTH


@dataclass(frozen=True)
class Strength:
    level: str  # "red" | "yellow" | "green"
    missing: tuple[str, ...] = field(default_factory=tuple)  # unmet recommendations


def check(password: str, *, admin: bool = False) -> str | None:
    """Return an error code when the password must be refused (red), else None."""
    if len(password) > config.PASSWORD_MAX_LENGTH:
        return "too_long"
    if len(password) < min_length(admin):
        return "too_short"
    if password.strip().lower() in _blocklist():
        return "blocklisted"
    return None


def strength(password: str, *, admin: bool = False) -> Strength:
    """Red = refused; yellow = accepted but a recommendation is unmet; green = none unmet."""
    if check(password, admin=admin) is not None:
        return Strength("red")
    green_length = max(config.PASSWORD_GREEN_LENGTH, min_length(admin))
    missing = []
    if len(password) < green_length:
        missing.append("length")
    if not any(ch.isdigit() for ch in password):
        missing.append("digit")
    if not any(not ch.isalnum() and not ch.isspace() for ch in password):
        missing.append("special")
    return Strength("yellow" if missing else "green", tuple(missing))
