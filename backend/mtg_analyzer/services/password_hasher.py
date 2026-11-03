"""Password hashing behind a small interface (PLR-9a, plan §3).

scrypt from the standard library is the zero-dependency default (OWASP-listed
alternative to Argon2id; `argon2-cffi` is not installed). The stored string
carries algorithm and parameters, so a parameter rise or a switch to Argon2id is
a rehash-on-login (`needs_rehash`), never a flag day.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading

from mtg_analyzer import config

#: OWASP scrypt baseline: N=2^17, r=8, p=1 (about 128 MiB per hash).
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_SALT_BYTES = 16
SCRYPT_KEY_BYTES = 32
#: hashlib refuses more than its default 32 MiB; scrypt needs 128*N*r bytes, this adds headroom.
SCRYPT_MAXMEM_FACTOR = 4

#: Hashing is memory-hard, so bound how many run at once (a login flood must not exhaust RAM).
MAX_CONCURRENT_HASHES = 2
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_HASHES)


class PasswordHasher:
    """scrypt hasher; `n` is overridable so tests do not pay 128 MiB per call."""

    algorithm = "scrypt"

    def __init__(self, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> None:
        self.n, self.r, self.p = n, r, p

    def _derive(self, password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
        # No truncation, trimming or case folding of the secret (plan §3).
        with _slots:
            return hashlib.scrypt(
                password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                maxmem=SCRYPT_MAXMEM_FACTOR * 128 * n * r, dklen=SCRYPT_KEY_BYTES,
            )

    def hash(self, password: str) -> str:
        if len(password) > config.PASSWORD_MAX_LENGTH:
            raise ValueError("password too long")
        salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
        key = self._derive(password, salt, self.n, self.r, self.p)
        enc = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
        return f"scrypt${self.n}${self.r}${self.p}${enc(salt)}${enc(key)}"

    def verify(self, password: str, stored: str) -> bool:
        if len(password) > config.PASSWORD_MAX_LENGTH:
            return False
        try:
            algo, n, r, p, salt, key = stored.split("$")
            if algo != "scrypt":
                return False
            expected = base64.b64decode(key)
            derived = self._derive(password, base64.b64decode(salt), int(n), int(r), int(p))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(derived, expected)

    def needs_rehash(self, stored: str) -> bool:
        try:
            algo, n, r, p, _salt, _key = stored.split("$")
            return (algo, int(n), int(r), int(p)) != (self.algorithm, self.n, self.r, self.p)
        except ValueError:
            return True

    def dummy_verify(self, password: str) -> None:
        """Burn comparable time for an unknown account so login timing does not reveal it."""
        self._derive(password, b"\0" * SCRYPT_SALT_BYTES, self.n, self.r, self.p)
