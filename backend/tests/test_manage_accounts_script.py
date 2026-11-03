"""PLR-9a: the OS-operator invitation command creates a redeemable token."""

import importlib.util
from pathlib import Path

from mtg_analyzer import config
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.password_hasher import PasswordHasher

_SPEC = importlib.util.spec_from_file_location(
    "manage_accounts", Path(__file__).resolve().parent.parent / "scripts" / "manage_accounts.py"
)
manage_accounts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(manage_accounts)


def test_operator_invite_is_redeemable_and_listed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "ACCOUNTS_DB_PATH", tmp_path / "accounts.db")
    assert manage_accounts.main(["invite"]) == 0
    token = capsys.readouterr().out.split("\n\n")[1].strip()
    store = AccountStore(tmp_path / "accounts.db")
    account = store.create_account_with_invitation("Alice", PasswordHasher(n=2 ** 4).hash("x"), token, "player")
    assert account.name == "Alice"
    manage_accounts.main(["list"])
    out = capsys.readouterr().out
    assert "used" in out and token not in out
