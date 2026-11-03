"""Test identity for routes that need a signed-in player (PLR-9b).

`tests/conftest.py` signs every API test in as `TEST_PLAYER_UUID` unless the test carries the
`real_auth` marker (the authorization matrix does and logs real accounts in).
"""

from __future__ import annotations

from mtg_analyzer.api.auth import AuthContext
from mtg_analyzer.services.account_store import ROLE_PLAYER, Account, Session

TEST_PLAYER_UUID = "test-player-0000"


def fake_context(player_uuid: str = TEST_PLAYER_UUID) -> AuthContext:
    account = Account(
        player_uuid=player_uuid, name="Tester", role=ROLE_PLAYER, disabled=False,
        setup_required=False, is_default_local=False, password_hash="!",
    )
    return AuthContext(account, Session(player_uuid, "csrf", 0.0, 1e12), "token")
