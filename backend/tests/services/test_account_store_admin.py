"""PLR-9d: account-store primitives for administration (migration 2, audit, recovery, deletion hand-off)."""

import asyncio

import pytest

from mtg_analyzer import config
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.account_store import AccountStore
from mtg_analyzer.services.lobby import Lobby
from mtg_analyzer.services.game_session import GameSessionManager


@pytest.fixture
def store(tmp_path):
    s = AccountStore(tmp_path / "a.db")
    yield s
    s.close()


def player(store, name="Alice"):
    return store.create_account_unchecked(name, "hash", acc.ROLE_PLAYER)


def test_migration_adds_the_admin_tables_to_an_existing_v1_database(tmp_path):
    path = tmp_path / "old.db"
    s = AccountStore(path)
    s._conn.execute("DROP TABLE meta")
    s._conn.execute("DROP TABLE audit_log")
    s._conn.execute("DROP TABLE recovery_credentials")
    s._conn.execute("PRAGMA user_version = 1")
    keep = player(s)
    s.close()
    again = AccountStore(path)  # additive migration, data kept
    assert again.schema_version == 2 and again.get(keep.player_uuid) is not None
    again.record_audit("x", "y")
    assert again.list_audit(limit=5)[1] == 1
    again.close()


def test_audit_text_is_bounded_and_control_characters_are_flattened(store):
    store.record_audit("a\nb\x00c", "act", "t" * 1000, "ok")
    entry = store.list_audit(limit=1)[0][0]
    assert "\n" not in entry["actor"] and "\x00" not in entry["actor"]
    assert len(entry["target"]) == acc.AUDIT_FIELD_MAX


def test_audit_is_newest_first_and_paginated(store):
    for i in range(5):
        store.record_audit("op", f"a{i}")
    entries, total = store.list_audit(limit=2, offset=1)
    assert total == 5 and [e["action"] for e in entries] == ["a3", "a2"]


def test_list_players_excludes_admins_and_filters_by_normalised_fragment(store):
    player(store, "Ärger"), player(store, "Bob")
    store.create_account_unchecked("boss", "h", acc.ROLE_ADMIN)
    rows, total = store.list_players("ÄR", limit=10)
    assert total == 1 and rows[0]["name"] == "Ärger"
    assert store.list_players(limit=10)[1] == 2


class TestRecovery:
    def test_single_use_replaces_the_password_and_revokes_sessions_without_login(self, store):
        alice = player(store)
        _token, _ = store.create_session(alice.player_uuid)
        credential = store.create_recovery(alice.player_uuid)
        assert store.redeem_recovery("alice", credential, "newhash", acc.ROLE_PLAYER) is True
        assert store.get(alice.player_uuid).password_hash == "newhash"
        assert store.list_sessions(alice.player_uuid) == []
        assert store.redeem_recovery("Alice", credential, "again", acc.ROLE_PLAYER) is False  # single use
        assert store.get(alice.player_uuid).password_hash == "newhash"

    def test_only_the_digest_is_stored(self, store):
        alice = player(store)
        credential = store.create_recovery(alice.player_uuid)
        dump = repr(store._conn.execute("SELECT * FROM recovery_credentials").fetchall()[0][:])
        assert credential not in dump

    def test_a_new_credential_invalidates_the_earlier_one(self, store):
        alice = player(store)
        first = store.create_recovery(alice.player_uuid)
        second = store.create_recovery(alice.player_uuid)
        assert store.redeem_recovery("Alice", first, "h", acc.ROLE_PLAYER) is False
        assert store.redeem_recovery("Alice", second, "h", acc.ROLE_PLAYER) is True

    def test_expiry_wrong_account_wrong_role_disabled_and_default_local_fail_alike(self, store):
        alice, bob = player(store), player(store, "Bobby")
        boss = store.create_account_unchecked("boss", "h", acc.ROLE_ADMIN)
        credential = store.create_recovery(alice.player_uuid)
        assert store.redeem_recovery("Bobby", credential, "h", acc.ROLE_PLAYER) is False  # not their credential
        assert store.redeem_recovery("Alice", credential, "h", acc.ROLE_ADMIN) is False  # wrong role endpoint
        admin_credential = store.create_recovery(boss.player_uuid)
        assert store.redeem_recovery("boss", admin_credential, "h", acc.ROLE_PLAYER) is False
        store.set_disabled(alice.player_uuid, True)
        assert store.redeem_recovery("Alice", credential, "h", acc.ROLE_PLAYER) is False
        store.set_disabled(alice.player_uuid, False)
        store._now = lambda: __import__("time").time() + config.RECOVERY_TTL_SECONDS + 1
        assert store.redeem_recovery("Alice", credential, "h", acc.ROLE_PLAYER) is False
        assert store.redeem_recovery("nobody", "x", "h", acc.ROLE_PLAYER) is False
        local = store.ensure_default_local()
        assert store.redeem_recovery("local", store.create_recovery(local.player_uuid), "h", acc.ROLE_PLAYER) is False


def test_deleted_accounts_are_handed_to_the_sweeper_once(store):
    alice = player(store)
    store.delete_account(alice.player_uuid)
    assert store.drain_deleted() == [alice.player_uuid] and store.drain_deleted() == []


def test_sweeper_frees_the_seat_of_a_deleted_account_without_the_disconnect_grace(store):
    from mtg_analyzer.api.multiplayer_ws import sweep_once

    alice, bob = player(store), player(store, "Bobby")
    lobby = Lobby()
    a = lobby.connect(alice.player_uuid, "Alice")
    b = lobby.connect(bob.player_uuid, "Bobby")
    game = lobby.create(a.id, "t", 2)
    lobby.join(game.id, b.id)
    store.delete_account(alice.player_uuid)
    asyncio.run(sweep_once(lobby, GameSessionManager(), store))
    assert lobby.find(a.id) is None and lobby.player_for_account(alice.player_uuid) is None
    assert lobby.find(b.id) is not None


def test_game_sessions_owned_by_an_account_are_removed_but_table_sessions_are_kept():
    class Fake:
        def __init__(self, sid, owner):
            self.id, self.owner = sid, owner

    manager = GameSessionManager()
    for sid, owner in (("mine", "u1"), ("table", "u1"), ("other", "u2")):
        manager._sessions[sid] = Fake(sid, owner)
        manager._last_access[sid] = 0.0
    manager.set_protected_provider(lambda: {"table"})
    assert manager.remove_owned_by("u1") == 1
    assert set(manager._sessions) == {"table", "other"}
    assert manager.remove_owned_by("") == 0
