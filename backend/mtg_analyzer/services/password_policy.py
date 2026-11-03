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


def _is_trivial(password: str) -> bool:
    """One repeated character, or a pure ascending/descending run ("abcdefghij", "9876543210")."""
    codes = [ord(ch) for ch in password.lower()]
    if len(set(codes)) == 1:
        return True
    steps = {b - a for a, b in zip(codes, codes[1:])}
    return steps == {1} or steps == {-1}


def check(password: str, *, admin: bool = False, name: str | None = None) -> str | None:
    """Return an error code when the password must be refused (red), else None.

    `name` is the account name: a password equal to it is refused (context-specific word)."""
    if len(password) > config.PASSWORD_MAX_LENGTH:
        return "too_long"
    if len(password) < min_length(admin):
        return "too_short"
    folded = password.strip().lower()
    if folded in _blocklist() or _is_trivial(password):
        return "blocklisted"
    if name and folded == name.strip().lower():
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
