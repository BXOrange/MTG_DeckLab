"""Peer-address allowlist for the run modes (PLR-9a, plan §1/§3).

LAN mode accepts only loopback plus either the operator's `MTG_ALLOWED_NETWORKS`
(complete list when set) or the subnets of the host's attached interfaces. Interface
enumeration needs `psutil`; without it the list is **loopback only** (fail-closed,
never a wider private range). The allowlist is a convenience boundary, not
authentication: accounts stay mandatory.

The client address is the ASGI peer only. `X-Forwarded-For` and `Forwarded` are never
trusted for the LAN allowlist; a request carrying them is not "local" for the admin and
default-localuser gates (`is_local_request`).

Behind `--behind-tls-proxy` (BUG-52) `X-Forwarded-Proto`/`X-Forwarded-For` are honoured only
from the configured trusted proxy peers (`config.TRUSTED_PROXIES`); from anyone else they are
ignored. In that mode nothing is "local": remote and on-machine admin alike go through the
proxy over HTTPS with TOTP, and a trusted-proxy request without `X-Forwarded-For` is refused.
The exception is the dedicated loopback-only admin listener (`--admin-port`, PLR-19): a request
that arrived on it is local by construction and needs no second factor.
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


_trusted_cache: tuple[str, list[Network]] = ("", [])


def trusted_proxy_networks() -> list[Network]:
    """The configured trusted-proxy networks; an unparsable list trusts nobody (fail-closed)."""
    global _trusted_cache
    raw = config.TRUSTED_PROXIES
    if _trusted_cache[0] != raw:
        try:
            nets = parse_networks(raw)
        except InvalidNetworkError:
            logger.error("invalid MTG_TRUSTED_PROXIES %r: no proxy is trusted", raw)
            nets = []
        _trusted_cache = (raw, nets)
    return _trusted_cache[1]


def is_trusted_proxy(peer: Optional[str]) -> bool:
    """Proxy mode only: the TCP peer is one of the operator's trusted reverse proxies (RFC 7239 trust is per hop)."""
    return config.BEHIND_TLS_PROXY and peer_allowed(peer, trusted_proxy_networks())


def _last_entry(value: str) -> str:
    """Right-most element of a comma-separated forwarding header.

    A trusted proxy appends what it saw to the end; everything to the left was supplied by the
    client (or an earlier hop) and is spoofable, so the right-most entry is the only one believed."""
    return value.rsplit(",", 1)[-1].strip()


def forwarded_proto(peer: Optional[str], headers: dict[str, str]) -> str:
    """`X-Forwarded-Proto` as set by a trusted proxy; "" from any other peer or when absent."""
    if not is_trusted_proxy(peer):
        return ""
    return _last_entry(headers.get("x-forwarded-proto", "")).lower()


def forwarded_client(peer: Optional[str], headers: dict[str, str]) -> Optional[str]:
    """The client address a trusted proxy reports in `X-Forwarded-For`; None when untrusted, absent or not an IP."""
    if not is_trusted_proxy(peer):
        return None
    addr = normalize_peer(_last_entry(headers.get("x-forwarded-for", "")))
    return str(addr) if addr is not None else None


#: ASGI scope key set by the dedicated local admin listener (`api/admin_listener.py`, PLR-19) and
#: by nothing else. It is not a header: a client cannot send it, only the listener's own wrapper
#: sets it, and that wrapper is attached solely to a socket bound to loopback.
ADMIN_LISTENER_SCOPE_KEY = "mtg.admin_listener"


def is_local_request(peer: Optional[str], headers: dict[str, str], *, admin_listener: bool = False) -> bool:
    """Loopback peer, no forwarding headers, loopback Host: the gate for /admin and the default-localuser.

    Never true in proxy mode (BUG-52): a same-host proxy with default settings sends exactly this
    shape (loopback peer, `Host: 127.0.0.1`), so the headers cannot prove the request is not an
    internet one. The one exception is a request that arrived on the dedicated loopback-only admin
    listener (`admin_listener`, PLR-19): which socket it came in on proves locality, so proxy mode
    does not matter, while the peer, header and Host checks still apply."""
    if (config.BEHIND_TLS_PROXY and not admin_listener) or not is_loopback(peer) \
            or any(h in headers for h in FORWARDING_HEADERS):
        return False
    host = headers.get("host", "").strip().lower()
    host = host[1:].split("]", 1)[0] if host.startswith("[") else host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host in ("localhost", "127.0.0.1", "::1")


#: Refusal codes of the admin surface (`admin_surface_refusal`).
ADMIN_LOCAL_ONLY = "admin_local_only"
ADMIN_HTTPS_REQUIRED = "admin_https_required"
ADMIN_FORWARDED_FOR_REQUIRED = "admin_forwarded_for_required"


def secure_transport(scheme: str, headers: dict[str, str], peer: Optional[str] = None) -> bool:
    """Whether the request provably arrived over TLS.

    The app terminates TLS itself (`--tls-cert`): the ASGI scheme is `https`. Behind a reverse
    proxy (`--behind-tls-proxy`, `config.BEHIND_TLS_PROXY`) the backend sees plain HTTP and the
    operator-declared proxy says so in `X-Forwarded-Proto`; that header is trusted only then, and
    only when the TCP peer is a trusted proxy (BUG-52); a direct request cannot vouch for itself."""
    if scheme.lower() in ("https", "wss"):
        return True
    return forwarded_proto(peer, headers) == "https"


def admin_surface_refusal(
    peer: Optional[str], headers: dict[str, str], scheme: str, *, admin_listener: bool = False
) -> Optional[str]:
    """Why `/admin` and `/api/admin` refuse this request, or None when it may proceed (PLR-9d).

    A genuinely local request (loopback peer, no forwarding headers, loopback Host) is always
    allowed. Anything else is refused in `lan` and `localdev`; in `--online` it is allowed **only
    over HTTPS** (credentials and the authenticator code must never cross plain HTTP). MFA is
    enforced separately, in `api/admin_auth.py`; a local request needs no second factor (PLR-19)."""
    if is_local_request(peer, headers, admin_listener=admin_listener):
        return None
    if admin_listener or config.RUN_MODE != "online":  # the admin listener is plain loopback HTTP: local or nothing
        return ADMIN_LOCAL_ONLY
    if is_trusted_proxy(peer) and forwarded_client(peer, headers) is None:
        # A correct proxy always names the client; a missing/garbled entry means a misconfigured
        # proxy (or a local process posing as one): refuse rather than guess (BUG-52).
        return ADMIN_FORWARDED_FOR_REQUIRED
    return None if secure_transport(scheme, headers, peer) else ADMIN_HTTPS_REQUIRED


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
