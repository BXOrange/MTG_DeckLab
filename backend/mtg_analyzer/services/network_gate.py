"""Peer-address allowlist for the run modes (PLR-9a, plan §1/§3).

LAN mode accepts only loopback plus either the operator's `MTG_ALLOWED_NETWORKS`
(complete list when set) or the subnets of the host's attached interfaces. Interface
enumeration needs `psutil`; without it the list is **loopback only** (fail-closed,
never a wider private range). The allowlist is a convenience boundary, not
authentication: accounts stay mandatory.

The client address is the ASGI peer only. `X-Forwarded-For` and `Forwarded` are never
trusted; a request carrying them is not "local" for the admin and default-localuser
gates (`is_local_request`).
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Iterable, Optional, Union

from mtg_analyzer import config

logger = logging.getLogger(__name__)

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

LOOPBACK_NETWORKS: tuple[Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)

#: Headers a reverse proxy adds; their presence means the TCP peer is not the real client.
FORWARDING_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")


class InvalidNetworkError(ValueError):
    """An operator CIDR could not be parsed: a startup error, never silently ignored."""


def parse_networks(csv: str) -> list[Network]:
    networks = []
    for part in csv.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError as exc:
            raise InvalidNetworkError(f"invalid MTG_ALLOWED_NETWORKS entry {part!r}") from exc
    return networks


def interface_networks() -> list[Network]:
    """Subnets of the attached interfaces (VPN included); [] when they cannot be listed."""
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("psutil is not installed: interface subnets unknown, LAN allowlist is loopback only")
        return []
    networks: list[Network] = []
    try:
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if not addr.netmask or "%" in addr.address:
                    continue
                try:
                    networks.append(ipaddress.ip_network(f"{addr.address}/{addr.netmask}", strict=False))
                except ValueError:
                    continue
    except Exception:  # enumeration must never widen access or block startup
        logger.exception("network interface enumeration failed: LAN allowlist is loopback only")
        return []
    return networks


def build_allowlist(mode: str, configured: str, interfaces=interface_networks) -> Optional[list[Network]]:
    """None = no peer gate (online); otherwise the networks a peer must belong to."""
    if mode == "online":
        return None
    if mode == "localdev":
        return list(LOOPBACK_NETWORKS)
    extra = parse_networks(configured)
    return list(LOOPBACK_NETWORKS) + (extra if extra else interfaces())


def normalize_peer(host: Optional[str]) -> Optional[Address]:
    """Parse the ASGI peer, unmapping `::ffff:a.b.c.d` and dropping a zone id."""
    if not host:
        return None
    host = host.split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def is_loopback(peer: Optional[str]) -> bool:
    addr = normalize_peer(peer)
    return addr is not None and addr.is_loopback


def peer_allowed(peer: Optional[str], allowlist: Optional[Iterable[Network]]) -> bool:
    if allowlist is None:
        return True
    addr = normalize_peer(peer)
    if addr is None:
        return False
    return any(addr.version == net.version and addr in net for net in allowlist)


def is_local_request(peer: Optional[str], headers: dict[str, str]) -> bool:
    """Loopback peer, no forwarding headers, loopback Host: the gate for /admin and the default-localuser."""
    if not is_loopback(peer) or any(h in headers for h in FORWARDING_HEADERS):
        return False
    host = headers.get("host", "").strip().lower()
    host = host[1:].split("]", 1)[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in ("localhost", "127.0.0.1", "::1")


#: Refusal codes of the admin surface (`admin_surface_refusal`).
ADMIN_LOCAL_ONLY = "admin_local_only"
ADMIN_HTTPS_REQUIRED = "admin_https_required"


def secure_transport(scheme: str, headers: dict[str, str]) -> bool:
    """Whether the request provably arrived over TLS.

    The app terminates TLS itself (`--tls-cert`): the ASGI scheme is `https`. Behind a reverse
    proxy (`--behind-tls-proxy`, `config.BEHIND_TLS_PROXY`) the backend sees plain HTTP and the
    operator-declared proxy says so in `X-Forwarded-Proto`; that header is trusted only then, and
    only on the premise that the proxy is the sole way in (SERVER_GUIDE)."""
    if scheme.lower() in ("https", "wss"):
        return True
    if config.BEHIND_TLS_PROXY:
        forwarded = headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
        return forwarded == "https"
    return False


def admin_surface_refusal(peer: Optional[str], headers: dict[str, str], scheme: str) -> Optional[str]:
    """Why `/admin` and `/api/admin` refuse this request, or None when it may proceed (PLR-9d).

    A genuinely local request (loopback peer, no forwarding headers, loopback Host) is always
    allowed. Anything else is refused in `lan` and `localdev`; in `--online` it is allowed **only
    over HTTPS** (credentials and the authenticator code must never cross plain HTTP). MFA is
    enforced separately, in `api/admin_auth.py`."""
    if is_local_request(peer, headers):
        return None
    if config.RUN_MODE != "online":
        return ADMIN_LOCAL_ONLY
    return None if secure_transport(scheme, headers) else ADMIN_HTTPS_REQUIRED


_active: Optional[list[Network]] = None
_resolved = False


def active_allowlist() -> Optional[list[Network]]:
    """Resolved once at first use; None when no explicit mode (ungated) or online."""
    global _active, _resolved
    if not _resolved:
        _active = build_allowlist(config.RUN_MODE, config.ALLOWED_NETWORKS) if config.RUN_MODE_EXPLICIT else None
        _resolved = True
        if _active is not None:
            logger.warning("peer allowlist (%s mode): %s", config.RUN_MODE, ", ".join(str(n) for n in _active))
    return _active


def reset_for_tests() -> None:
    global _active, _resolved
    _active, _resolved = None, False
