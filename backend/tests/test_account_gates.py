"""PLR-9e: section 8 gates that had no test of their own (restart survival, concurrent signup, CORS)."""

import threading

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.services import account_crypto as crypto
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher

FAST = PasswordHasher(n=2 ** 4)


def test_sessions_survive_a_backend_restart(tmp_path):
    """The encrypted store reopened with the same key still resolves a session issued before."""
    path, key = tmp_path / "accounts.db", crypto.new_key()
    first = AccountStore(path, key=key)
    account = first.create_account_unchecked("Persistent", FAST.hash("x"), "player")
    token, _ = first.create_session(account.player_uuid)
    first.close()
    second = AccountStore(path, key=key)
    resolved = second.resolve_session(token)
    assert resolved is not None and resolved[0].player_uuid == account.player_uuid
    second.close()


def test_concurrent_signups_of_one_normalized_name_create_one_account(tmp_path):
    store = AccountStore(tmp_path / "accounts.db", key=crypto.new_key())
    admin = store.create_account_unchecked("boss-admin", FAST.hash("x"), "admin")
    tokens = [store.create_invitation(admin.player_uuid, "player", enforce_limits=False) for _ in range(6)]
    outcomes = []

    def signup(index):
        name = "Racer" if index % 2 else "RACER"  # same name after case folding
        try:
            outcomes.append(store.create_account_with_invitation(name, FAST.hash("pw"), tokens[index], "player"))
        except acc.AccountError as exc:
            outcomes.append(exc)

    threads = [threading.Thread(target=signup, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(isinstance(o, acc.Account) for o in outcomes) == 1
    assert all(isinstance(o, acc.NameTakenError) for o in outcomes if not isinstance(o, acc.Account))
    assert store.count_accounts("player") == 1
    store.close()


def test_a_foreign_origin_gets_no_cors_grant_even_with_credentials():
    client = TestClient(app)
    for origin in ("https://evil.example", "http://192.168.1.50:8000"):
        simple = client.get("/api/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in simple.headers
        # `Allow-Credentials: true` alone is inert: browsers need a matching Allow-Origin to expose the response.
        preflight = client.options(
            "/api/auth/login",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in preflight.headers
