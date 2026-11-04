"""PLR-9a: account storage, sessions, invitations, password policy and hashing."""

import threading

import pytest

from mtg_analyzer import config
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services.password_hasher import PasswordHasher
from mtg_analyzer.services import password_policy as policy

FAST = PasswordHasher(n=2 ** 4)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return acc.AccountStore(tmp_path / "accounts.db", clock=clock)


def _signup(store, name="Alice", role="player"):
    admin = store.get_by_name("inviter-admin") or store.create_account_unchecked("inviter-admin", FAST.hash("x"), "admin")
    token = store.create_invitation(admin.player_uuid, role, enforce_limits=False)
    return store.create_account_with_invitation(name, FAST.hash("pw"), token, role)


def test_migrations_are_versioned_and_idempotent(tmp_path):
    first = acc.AccountStore(tmp_path / "a.db")
    version = first.schema_version
    first.close()
    assert acc.AccountStore(tmp_path / "a.db").schema_version == version >= 1


def test_name_unique_after_normalisation(store):
    _signup(store, "Alice")
    with pytest.raises(acc.NameTakenError):
        _signup(store, "ALICE")
    with pytest.raises(acc.NameTakenError):
        _signup(store, "ａlice")  # fullwidth NFKC collision


@pytest.mark.parametrize("name", ["ab", "x" * 33, "local", "Admin", "bad\x00name", "two  spaces"])
def test_invalid_names_refused(store, name):
    with pytest.raises(acc.InvalidNameError):
        acc.validate_name(name)


def test_invitation_is_single_use_and_atomic(store):
    admin = store.create_account_unchecked("boss-admin", FAST.hash("x"), "admin")
    token = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    results = []

    def redeem(n):
        try:
            results.append(store.create_account_with_invitation(f"racer{n}", FAST.hash("pw"), token, "player"))
        except acc.AccountError as exc:
            results.append(exc)

    threads = [threading.Thread(target=redeem, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sum(isinstance(r, acc.Account) for r in results) == 1
    assert store.count_accounts("player") == 1


def test_taken_name_does_not_burn_the_token(store):
    _signup(store, "Alice")
    admin = store.get_by_name("inviter-admin")
    token = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    with pytest.raises(acc.NameTakenError):
        store.create_account_with_invitation("alice", FAST.hash("pw"), token, "player")
    assert store.create_account_with_invitation("bob", FAST.hash("pw"), token, "player").name == "bob"


def test_invitation_failures_are_indistinguishable(store, clock):
    admin = store.create_account_unchecked("boss-admin", FAST.hash("x"), "admin")
    expired = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    clock.t += config.INVITE_TTL_SECONDS + 1
    revoked = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    store.revoke_invitation(acc._digest(revoked), by=admin.player_uuid, is_admin=True)
    wrong_role = store.create_invitation(admin.player_uuid, "admin", enforce_limits=False)
    for token, role in [("nonsense", "player"), (expired, "player"), (revoked, "player"), (wrong_role, "player")]:
        with pytest.raises(acc.InvalidInvitationError):
            store.create_account_with_invitation("carol", FAST.hash("pw"), token, role)


def test_disabled_creator_invalidates_open_tokens(store):
    alice = _signup(store, "Alice")
    token = store.create_invitation(alice.player_uuid, "player")
    store.set_disabled(alice.player_uuid, True)
    with pytest.raises(acc.InvalidInvitationError):
        store.create_account_with_invitation("dave", FAST.hash("pw"), token, "player")


def test_player_invitation_limits(store, monkeypatch):
    monkeypatch.setattr(config, "INVITE_MAX_OUTSTANDING_PER_PLAYER", 2)
    alice = _signup(store, "Alice")
    store.create_invitation(alice.player_uuid, "player")
    store.create_invitation(alice.player_uuid, "player")
    with pytest.raises(acc.InvitationLimitError):
        store.create_invitation(alice.player_uuid, "player")


def test_invitation_listing_never_exposes_the_token(store):
    admin = store.create_account_unchecked("boss-admin", FAST.hash("x"), "admin")
    token = store.create_invitation(admin.player_uuid, "player", enforce_limits=False)
    listing = store.list_invitations()
    assert token not in repr(listing)
    assert listing[0]["state"] == "open"


def test_session_lifecycle(store, clock):
    alice = _signup(store, "Alice")
    token, session = store.create_session(alice.player_uuid)
    assert store.resolve_session(token)[0].player_uuid == alice.player_uuid
    assert store.resolve_session("bogus") is None
    # only the digest is stored
    assert token not in repr(store._conn.execute("SELECT * FROM sessions").fetchall()[0][0])
    clock.t += config.SESSION_IDLE_SECONDS + 1
    assert store.resolve_session(token) is None


def test_session_valid_reports_state_without_sliding_the_window(store, clock):
    # PLR-9c: long-lived sockets poll this; polling must never keep a session alive.
    alice = _signup(store, "Alice")
    token, session = store.create_session(alice.player_uuid)
    assert store.session_valid(token) and not store.session_valid("bogus") and not store.session_valid("")
    clock.t += config.SESSION_IDLE_SECONDS - 1
    assert store.session_valid(token)
    clock.t += 2  # no resolve_session happened in between, so the idle window was not renewed
    assert not store.session_valid(token)
    fresh, _ = store.create_session(alice.player_uuid)
    store.set_disabled(alice.player_uuid, True)
    assert not store.session_valid(fresh)
    store.set_disabled(alice.player_uuid, False)
    store.revoke_session(fresh)
    assert not store.session_valid(fresh)


def test_absolute_session_limit_beats_sliding_idle(store, clock, monkeypatch):
    monkeypatch.setattr(config, "SESSION_ABSOLUTE_SECONDS", 1000.0)
    monkeypatch.setattr(config, "SESSION_IDLE_SECONDS", 600.0)
    alice = _signup(store, "Alice")
    token, _ = store.create_session(alice.player_uuid)
    for _ in range(2):
        clock.t += 400
        assert store.resolve_session(token) is not None
    clock.t += 400
    assert store.resolve_session(token) is None


def test_logout_disable_and_password_change_revoke_sessions(store):
    alice = _signup(store, "Alice")
    keep, _ = store.create_session(alice.player_uuid)
    other, _ = store.create_session(alice.player_uuid)
    store.set_password(alice.player_uuid, FAST.hash("new-password-1"), keep_session=keep)
    assert store.resolve_session(keep) is not None
    assert store.resolve_session(other) is None
    store.revoke_session(keep)
    assert store.resolve_session(keep) is None
    token, _ = store.create_session(alice.player_uuid)
    store.set_disabled(alice.player_uuid, True)
    assert store.resolve_session(token) is None


def test_deleted_name_is_tombstoned_then_free(store, clock, monkeypatch):
    alice = _signup(store, "Alice")
    store.delete_account(alice.player_uuid)
    with pytest.raises(acc.NameTakenError):
        _signup(store, "Alice")
    clock.t += config.NAME_TOMBSTONE_SECONDS + 1
    again = _signup(store, "Alice")
    assert again.player_uuid != alice.player_uuid


def test_seed_may_use_reserved_names(store):
    seed = store.create_account_unchecked("admin", FAST.hash("admin"), "admin", setup_required=True)
    assert seed.setup_required
    store.set_password(seed.player_uuid, FAST.hash("a-long-valid-password"))
    assert not store.get(seed.player_uuid).setup_required


# -- hashing and policy ---------------------------------------------------

def test_hasher_roundtrip_unicode_and_rehash():
    h = FAST.hash("pässwörd 密码 with spaces ")
    assert FAST.verify("pässwörd 密码 with spaces ", h)
    assert not FAST.verify("pässwörd 密码 with spaces", h)  # no trimming
    assert not FAST.verify("x", "garbage")
    assert PasswordHasher(n=2 ** 5).needs_rehash(h)
    assert not FAST.needs_rehash(h)


@pytest.mark.parametrize("pw,admin,error", [
    ("ab" * 4 + "a", False, "too_short"), ("ab" * 5, False, None),
    ("ab" * 7, True, "too_short"), ("ab" * 7 + "a", True, None),
    ("password123", False, "blocklisted"), ("x" * 2000, False, "too_long"),
])
def test_policy_boundaries(pw, admin, error):
    assert policy.check(pw, admin=admin) == error


def test_strength_classes():
    assert policy.strength("short").level == "red"
    assert policy.strength("longenoughpw").missing == ("digit", "special")
    assert policy.strength("longenough1!").level == "green"
    assert policy.strength("abcdefghi!1").level == "yellow"  # 11 chars: length recommendation unmet
    assert policy.strength("abcdefghij1!").level == "green"
    assert policy.strength("a long passphrase no digits").level == "yellow"


def test_trivial_and_name_passwords_are_refused():
    assert policy.check("a" * 12) == "blocklisted"            # one repeated character
    assert policy.check("abcdefghijkl") == "blocklisted"      # ascending run
    assert policy.check("9876543210") == "blocklisted"        # descending run
    assert policy.check("Magic Player 1", name="magic player 1") == "blocklisted"
    assert policy.check("Magic Player 1", name="someone else") is None
    assert policy.check("MAGICTHEGATHERING") == "blocklisted"  # case-insensitive list
