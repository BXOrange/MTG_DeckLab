"""Time-based one-time passwords (RFC 6238 over RFC 4226) for admin MFA (PLR-9d, plan section 6).

Standard library only (`hmac`, `hashlib`, `base64`, `struct`): 6 digits, 30 second step,
HMAC-SHA1, because every authenticator app implements exactly that profile. This module is pure:
it knows nothing about accounts. Replay protection (a time step is accepted at most once per
admin) lives in `AccountStore.consume_totp`, which persists the last accepted step.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from typing import Optional
from urllib.parse import quote

from mtg_analyzer import config

#: Bytes of entropy in a new shared secret. RFC 4226 section 4 asks for at least 128 bits and
#: recommends 160; 20 bytes is also exactly 32 base32 characters (no padding).
SECRET_BYTES = 20

#: RFC 4226 section 5.3 dynamic truncation: the low nibble of the last byte picks a 4-byte window,
#: and its top bit is masked so the result is a non-negative 31-bit integer.
_OFFSET_MASK = 0x0F
_SIGN_MASK = 0x7FFFFFFF

#: `issuer` of the provisioning URI (shown by the authenticator app next to the account).
ISSUER = "DeckLab"


def new_secret() -> str:
    """A fresh shared secret as unpadded base32 (what authenticator apps ask for)."""
    return base64.b32encode(secrets.token_bytes(SECRET_BYTES)).decode("ascii").rstrip("=")


def _key(secret_b32: str) -> bytes:
    padded = secret_b32.strip().replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    return base64.b32decode(padded)


def hotp(secret_b32: str, counter: int, digits: int = config.TOTP_DIGITS) -> str:
    """RFC 4226 HOTP value of ``counter`` as a zero-padded string."""
    digest = hmac.new(_key(secret_b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & _OFFSET_MASK
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & _SIGN_MASK
    return str(number % (10 ** digits)).zfill(digits)


def time_step(now: float, period: int = config.TOTP_PERIOD_SECONDS) -> int:
    """The RFC 6238 counter T = floor(unix time / period)."""
    return int(now // period)


def totp(secret_b32: str, now: float, *, digits: int = config.TOTP_DIGITS,
         period: int = config.TOTP_PERIOD_SECONDS) -> str:
    return hotp(secret_b32, time_step(now, period), digits)


def looks_like_code(text: str) -> bool:
    """Whether ``text`` has the shape of a TOTP code (digits only, once spaces are dropped)."""
    cleaned = text.replace(" ", "")
    return len(cleaned) == config.TOTP_DIGITS and cleaned.isdigit()


def match_step(secret_b32: str, code: str, now: float, *, skew: int = config.TOTP_SKEW_STEPS) -> Optional[int]:
    """The time step ``code`` is valid for within +/- ``skew`` steps of ``now``, else None.

    Every candidate is compared in constant time and all of them are evaluated, so timing does
    not reveal which step (or how many digits) matched. The newest matching step wins."""
    cleaned = code.replace(" ", "")
    if not looks_like_code(cleaned):
        return None
    current = time_step(now)
    found: Optional[int] = None
    for step in range(current - skew, current + skew + 1):
        if hmac.compare_digest(hotp(secret_b32, step), cleaned):
            found = step
    return found


def provisioning_uri(secret_b32: str, account_name: str) -> str:
    """The `otpauth://` URI an authenticator app imports (shown as text on /admin: strict CSP, no QR)."""
    label = quote(f"{ISSUER}:{account_name}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(ISSUER, safe='')}"
        f"&algorithm=SHA1&digits={config.TOTP_DIGITS}&period={config.TOTP_PERIOD_SECONDS}"
    )


# -- recovery codes -------------------------------------------------------------------------

#: Characters of a recovery code per hyphen-separated group (cosmetic: easier to copy by hand).
_RECOVERY_GROUP = 4


def new_recovery_codes(count: int = config.ADMIN_RECOVERY_CODE_COUNT) -> list[str]:
    """``count`` single-use codes of ``ADMIN_RECOVERY_CODE_BYTES`` bytes of entropy, grouped for readability."""
    codes = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(config.ADMIN_RECOVERY_CODE_BYTES)).decode("ascii").rstrip("=")
        codes.append("-".join(raw[i:i + _RECOVERY_GROUP] for i in range(0, len(raw), _RECOVERY_GROUP)))
    return codes


def normalize_recovery_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def recovery_digest(code: str) -> str:
    """What is stored of a recovery code: the SHA-256 of its normalised form (80-bit codes, never the code)."""
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
