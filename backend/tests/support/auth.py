"""Test identity for routes that need a signed-in player (PLR-9b, PLR-9c).

`tests/conftest.py` signs every API test in as `TEST_PLAYER_UUID` unless the test carries the
`real_auth` marker (the authorization matrix does and logs real accounts in). A test that needs
several players (multiplayer) names the account per request with the `X-Test-Account` header
(`account_header`); the account store behind it is always a throwaway in-memory one, never
`data/accounts.db`.
"""

from __future__ import annotations

from mtg_analyzer.api.auth import AuthContext
from mtg_analyzer.services.account_store import ROLE_PLAYER, Account, AccountStore, Session

TEST_PLAYER_UUID = "test-player-0000"

#: Header a test client sets to choose which fake account a request is made as: "<uuid>|<name>".
ACCOUNT_HEADER = "x-test-account"

#: Prefix of every fake session token; `ScratchAccountStore` treats these as live sessions.
FAKE_TOKEN_PREFIX = "test-token-"


def account_header(name: str, player_uuid: str | None = None) -> dict[str, str]:
    """Request headers that make a request come from the fake account ``name``."""
    return {ACCOUNT_HEADER: f"{player_uuid or 'uuid-' + name.casefold()}|{name}"}


def fake_context(player_uuid: str = TEST_PLAYER_UUID, name: str = "Tester") -> AuthContext:
    account = Account(
        player_uuid=player_uuid, name=name, role=ROLE_PLAYER, disabled=False,
        setup_required=False, is_default_local=False, password_hash="!",
    )
    return AuthContext(account, Session(player_uuid, "csrf", 0.0, 1e12), f"{FAKE_TOKEN_PREFIX}{player_uuid}")


def context_from_headers(headers) -> AuthContext:
    """The fake account a request names via `ACCOUNT_HEADER` (default: `TEST_PLAYER_UUID`)."""
    raw = headers.get(ACCOUNT_HEADER)
    if not raw:
        return fake_context()
    player_uuid, _, name = raw.partition("|")
    return fake_context(player_uuid, name or "Tester")


class ScratchAccountStore(AccountStore):
    """In-memory store whose fake sessions (`FAKE_TOKEN_PREFIX`) count as live."""

    def __init__(self) -> None:
        super().__init__(":memory:")

    def session_valid(self, token: str) -> bool:
        return token.startswith(FAKE_TOKEN_PREFIX) or super().session_valid(token)
