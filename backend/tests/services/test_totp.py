"""PLR-9d: TOTP (RFC 6238), recovery codes and the replay-protected second factor in the account store.

Time is injected through the store's clock; nothing sleeps and nothing touches ``data/*.db``.
"""

import base64

import pytest

from mtg_analyzer import config
from mtg_analyzer.services import account_store as acc
from mtg_analyzer.services import totp
from mtg_analyzer.services.account_store import AccountStore

#: RFC 6238 appendix B: the SHA-1 seed is the ASCII string "12345678901234567890"; vectors use 8 digits.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
RFC_VECTORS = [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130"),
]
T0 = 1_700_000_000.0  # an arbitrary fixed "now"; step boundaries are computed, never assumed


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    s = AccountStore(tmp_path / "accounts.db", clock=clock)
    yield s
    s.close()


@pytest.fixture
def admin(store):
    return store.create_account_unchecked("boss", "!", acc.ROLE_ADMIN)


def enrol(store, admin, clock):
    secret = totp.new_secret()
    store.begin_mfa_enrollment(admin.player_uuid, secret)
    codes = store.confirm_mfa_enrollment(admin.player_uuid, totp.totp(secret, clock.now))
    assert codes is not None
    return secret, codes


class TestRfc6238:
    @pytest.mark.parametrize("when,expected", RFC_VECTORS)
    def test_published_test_vectors(self, when, expected):
        assert totp.totp(RFC_SECRET, when, digits=8) == expected

    @pytest.mark.parametrize("when,expected", RFC_VECTORS)
    def test_the_six_digit_profile_is_the_tail_of_the_same_value(self, when, expected):
        assert config.TOTP_DIGITS == 6 and config.TOTP_PERIOD_SECONDS == 30
        assert totp.totp(RFC_SECRET, when) == expected[-6:]

    def test_secret_is_160_bit_unpadded_base32(self):
        secret = totp.new_secret()
        assert len(secret) == 32 and "=" not in secret
        assert len(base64.b32decode(secret)) == totp.SECRET_BYTES == 20
        assert totp.new_secret() != secret

    def test_provisioning_uri_is_text_with_the_standard_parameters(self):
        uri = totp.provisioning_uri("ABC234", "boss")
        assert uri.startswith("otpauth://totp/DeckLab%3Aboss?secret=ABC234")
        assert "issuer=DeckLab" in uri and "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


class TestSkewWindow:
    def test_neighbouring_steps_are_accepted_further_ones_are_not(self):
        step = totp.time_step(T0)
        for offset, ok in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
            code = totp.hotp(RFC_SECRET, step + offset)
            assert (totp.match_step(RFC_SECRET, code, T0) == step + offset) is ok, offset

    def test_window_is_the_named_constant(self):
        assert config.TOTP_SKEW_STEPS == 1

    @pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34", "      "])
    def test_malformed_codes_never_match(self, bad):
        assert totp.match_step(RFC_SECRET, bad, T0) is None

    def test_spaces_inside_a_code_are_tolerated(self):
        code = totp.totp(RFC_SECRET, T0)
        assert totp.match_step(RFC_SECRET, f"{code[:3]} {code[3:]}", T0) is not None


class TestReplayProtection:
    def test_a_code_is_accepted_once_per_admin(self, store, admin, clock):
        secret, _ = enrol(store, admin, clock)
        clock.now += config.TOTP_PERIOD_SECONDS * 5  # past the confirming code's step
        code = totp.totp(secret, clock.now)
        assert store.consume_second_factor(admin.player_uuid, code) == "totp"
        assert store.consume_second_factor(admin.player_uuid, code) is None

    def test_the_confirming_code_cannot_be_replayed_to_sign_in(self, store, admin, clock):
        secret, _ = enrol(store, admin, clock)
        assert store.consume_second_factor(admin.player_uuid, totp.totp(secret, clock.now)) is None

    def test_an_older_step_is_refused_after_a_newer_one(self, store, admin, clock):
        secret, _ = enrol(store, admin, clock)
        clock.now += config.TOTP_PERIOD_SECONDS * 5
        newer = totp.hotp(secret, totp.time_step(clock.now) + 1)  # inside the skew window
        older = totp.hotp(secret, totp.time_step(clock.now))
        assert store.consume_second_factor(admin.player_uuid, newer) == "totp"
        assert store.consume_second_factor(admin.player_uuid, older) is None

    def test_the_next_step_works_again(self, store, admin, clock):
        secret, _ = enrol(store, admin, clock)
        for _ in range(3):
            clock.now += config.TOTP_PERIOD_SECONDS * 3
            assert store.consume_second_factor(admin.player_uuid, totp.totp(secret, clock.now)) == "totp"

    def test_another_admins_secret_does_not_match(self, store, admin, clock):
        other = store.create_account_unchecked("second", "!", acc.ROLE_ADMIN)
        secret, _ = enrol(store, admin, clock)
        enrol(store, other, clock)
        clock.now += config.TOTP_PERIOD_SECONDS * 5
        assert store.consume_second_factor(other.player_uuid, totp.totp(secret, clock.now)) is None


class TestRecoveryCodes:
    def test_ten_distinct_80_bit_codes_stored_as_digests(self, store, admin, clock):
        _, codes = enrol(store, admin, clock)
        assert len(codes) == config.ADMIN_RECOVERY_CODE_COUNT == 10 and len(set(codes)) == 10
        rows = store._conn.execute("SELECT code_digest FROM admin_recovery_codes").fetchall()
        stored = {r["code_digest"] for r in rows}
        assert stored == {totp.recovery_digest(c) for c in codes}
        assert not any(c.replace("-", "") in blob for c in codes for blob in stored)
        assert config.ADMIN_RECOVERY_CODE_BYTES * 8 == 80

    def test_a_recovery_code_works_once_in_any_spelling(self, store, admin, clock):
        _, codes = enrol(store, admin, clock)
        assert store.consume_second_factor(admin.player_uuid, codes[0].lower().replace("-", " ")) == "recovery"
        assert store.consume_second_factor(admin.player_uuid, codes[0]) is None
        assert store.get_mfa(admin.player_uuid).recovery_codes_left == 9

    def test_codes_belong_to_their_admin(self, store, admin, clock):
        other = store.create_account_unchecked("second", "!", acc.ROLE_ADMIN)
        _, codes = enrol(store, admin, clock)
        enrol(store, other, clock)
        assert store.consume_second_factor(other.player_uuid, codes[0]) is None

    def test_regenerating_replaces_every_code(self, store, admin, clock):
        _, old = enrol(store, admin, clock)
        new = store.regenerate_recovery_codes(admin.player_uuid)
        assert store.consume_second_factor(admin.player_uuid, old[0]) is None
        assert store.consume_second_factor(admin.player_uuid, new[0]) == "recovery"


class TestEnrolmentState:
    def test_a_pending_secret_does_not_enrol_until_confirmed(self, store, admin, clock):
        secret = totp.new_secret()
        store.begin_mfa_enrollment(admin.player_uuid, secret)
        state = store.get_mfa(admin.player_uuid)
        assert state.pending and not state.enrolled
        assert store.consume_second_factor(admin.player_uuid, totp.totp(secret, clock.now)) is None

    def test_a_wrong_code_does_not_confirm(self, store, admin):
        store.begin_mfa_enrollment(admin.player_uuid, totp.new_secret())
        assert store.confirm_mfa_enrollment(admin.player_uuid, "123456") is None
        assert not store.get_mfa(admin.player_uuid).enrolled

    def test_replacement_keeps_the_old_secret_until_the_new_one_is_confirmed(self, store, admin, clock):
        old, _ = enrol(store, admin, clock)
        fresh = totp.new_secret()
        store.begin_mfa_enrollment(admin.player_uuid, fresh)
        assert store.mfa_secret(admin.player_uuid) == old
        clock.now += config.TOTP_PERIOD_SECONDS * 5
        assert store.confirm_mfa_enrollment(admin.player_uuid, totp.totp(fresh, clock.now)) is not None
        assert store.mfa_secret(admin.player_uuid) == fresh
        clock.now += config.TOTP_PERIOD_SECONDS * 5
        assert store.consume_second_factor(admin.player_uuid, totp.totp(old, clock.now)) is None

    def test_versions_only_increase_so_old_grants_never_revive(self, store, admin, clock):
        enrol(store, admin, clock)
        before = store.get_mfa(admin.player_uuid).version
        assert store.clear_mfa(admin.player_uuid)
        assert not store.get_mfa(admin.player_uuid).enrolled
        clock.now += config.TOTP_PERIOD_SECONDS * 5
        enrol(store, admin, clock)
        assert store.get_mfa(admin.player_uuid).version > before

    def test_mfa_rows_die_with_the_account(self, store, admin, clock):
        enrol(store, admin, clock)
        store.delete_account(admin.player_uuid)
        assert store._conn.execute("SELECT COUNT(*) FROM admin_totp").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM admin_recovery_codes").fetchone()[0] == 0
