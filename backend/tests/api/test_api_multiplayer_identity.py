"""PLR-9c: multiplayer identity, authenticated sockets and the single-session lock.

Reference: docs/concepts/15_ACCOUNT_SYSTEM_PLAN.md section 5, mtg_analyzer/api/multiplayer_ws.py.

The fake-account tests (`account_header`) exercise the socket protocol; the `real_auth` class
drives real sessions (cookie at upgrade, logout, expiry, disablement, deletion). Nothing here
touches `data/accounts.db`: the account store is always an in-memory one.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mtg_analyzer.api import multiplayer_ws as ws_module
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import session_cookie_name, websocket_context
from mtg_analyzer.api.dependencies import get_account_store, get_lobby
from mtg_analyzer.api.multiplayer_ws import manager, sweep_once
from mtg_analyzer.services.account_store import AccountStore
from tests.api.test_api_multiplayer import _connect, _drain_until, _seated_game, env, lobby_socket  # noqa: F401
from tests.support.auth import account_header


@pytest.fixture(autouse=True)
def _clean_connection_manager():
    """The manager is a process-wide singleton; start and end every test with it empty."""
    def reset():
        manager._sockets.clear()
        manager._by_account.clear()
        manager._tab_bindings.clear()
        manager._pending = 0

    reset()
    yield
    reset()


def _refused(client, headers, first_frame=None, raw=None):
    """Open a socket, send one handshake attempt, return the final ``disconnected`` frame."""
    with client.websocket_connect("/ws/lobby", headers=headers) as socket:
        if raw is not None:
            socket.send_text(raw)
        elif first_frame is not None:
            socket.send_json(first_frame)
        message = socket.receive_json()
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_json()
        assert closed.value.code == ws_module.WS_POLICY_VIOLATION
        return message


def _sweep(lobby, sessions, accounts=None):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(sweep_once(lobby, sessions, accounts))
    finally:
        loop.close()


class TestHandshake:
    def test_no_session_is_refused_before_anything_is_sent(self, env):
        app.dependency_overrides[websocket_context] = lambda: None
        try:
            message = _refused(env["client"], {})
        finally:
            app.dependency_overrides.pop(websocket_context, None)
        assert message["type"] == "disconnected" and message["reason"] == "unauthenticated"
        assert message["message"]  # VIS-24: the reason also carries a localized text
        assert env["lobby"].players() == []

    @pytest.mark.parametrize(
        ("headers", "needle"),
        [({}, "anmelden"), ({"cookie": "mtg_lang=en"}, "sign in"), ({"accept-language": "en-GB,en;q=0.8"}, "sign in")],
    )
    def test_disconnect_reason_message_follows_the_callers_language(self, env, headers, needle):
        """VIS-24: the final frame keeps the stable ``reason`` and adds a localized ``message``."""
        app.dependency_overrides[websocket_context] = lambda: None
        try:
            message = _refused(env["client"], headers)
        finally:
            app.dependency_overrides.pop(websocket_context, None)
        assert message["reason"] == "unauthenticated"
        assert needle in message["message"]

    def test_every_close_reason_has_a_localized_text(self):
        from mtg_analyzer.i18n import has_message

        reasons = {
            getattr(ws_module, name) for name in dir(ws_module) if name.startswith("REASON_")
        } - {ws_module.REASON_LOBBY_FULL}
        reasons |= {"replaced", "idle", "timeout"}  # literals passed to `manager.close`
        assert all(has_message(f"ws_{reason}") for reason in reasons)
        assert has_message(ws_module.REASON_LOBBY_FULL)

    @pytest.mark.parametrize(
        "frame, raw",
        [
            ({"type": "presence", "state": "available"}, None),  # wrong first message
            ({"type": "auth", "tab_id": 7}, None),  # tab id of the wrong type
            ({"type": "auth", "tab_id": "x" * 500}, None),  # tab id too long
            (None, "not json"),
            (None, '{"type": "auth", "pad": "' + "x" * 5000 + '"}'),  # oversize
            (None, "[1, 2]"),  # not an object
        ],
    )
    def test_a_malformed_first_frame_is_refused_and_registers_nobody(self, env, frame, raw):
        message = _refused(env["client"], account_header("Ann"), frame, raw)
        assert message["reason"] == "auth_required"
        assert env["lobby"].players() == []
        assert manager._pending == 0

    def test_a_silent_socket_is_dropped_after_the_timeout(self, env, monkeypatch):
        monkeypatch.setattr(ws_module, "AUTH_FRAME_TIMEOUT_SECONDS", 0.05)
        message = _refused(env["client"], account_header("Ann"))
        assert message["reason"] == "auth_required"
        assert env["lobby"].players() == []

    def test_a_wrong_csrf_proof_is_refused_and_the_right_one_accepted(self, env):
        assert _refused(env["client"], account_header("Ann"), {"type": "auth", "csrf_token": "no"})[
            "reason"
        ] == "unauthenticated"
        with env["client"].websocket_connect("/ws/lobby", headers=account_header("Ann")) as socket:
            socket.send_json({"type": "auth", "csrf_token": "csrf"})  # the fake session's token
            assert socket.receive_json()["type"] == "welcome"

    def test_unauthenticated_sockets_are_capped(self, env, monkeypatch):
        monkeypatch.setattr(ws_module, "MAX_PENDING_SOCKETS", 0)
        with pytest.raises(WebSocketDisconnect):
            with env["client"].websocket_connect("/ws/lobby", headers=account_header("Ann")):
                pass
        assert env["lobby"].players() == []

    def test_no_legacy_credential_in_the_url_or_frame_reclaims_a_seat(self, env):
        client, lobby = env["client"], env["lobby"]
        gid, ann, bob = _seated_game(env)
        # Mallory names Ann's id, name, secret and a client token in every channel there was.
        with client.websocket_connect(
            f"/ws/lobby?name=Ann&player_id={ann}&client_token=tok", headers=account_header("Mallory")
        ) as socket:
            socket.send_json({"type": "auth", "secret": "guess", "player_id": ann})
            welcome = socket.receive_json()
        assert welcome["player_id"] not in (ann, bob)
        assert welcome["name"] == "Mallory"
        assert welcome["reclaimed"] is False
        assert lobby.player(ann).name == "Ann"


class TestMessageLimits:
    def test_a_flood_is_cut_off_with_rate_limited(self, env, monkeypatch):
        monkeypatch.setattr(ws_module, "WS_RATE_LIMIT_MESSAGES", 3)
        with lobby_socket(env["client"], "Ann") as (socket, welcome):
            for _ in range(6):
                socket.send_json({"type": "ping"})
            message = _drain_until(socket, "disconnected")
        assert message["reason"] == "rate_limited"
        assert not manager.is_connected(welcome["player_id"])

    def test_an_oversize_or_invalid_message_is_an_error_not_a_crash(self, env):
        with lobby_socket(env["client"], "Ann") as (socket, _welcome):
            socket.send_text("x" * (ws_module.WS_MAX_MESSAGE_CHARS + 1))
            assert _drain_until(socket, "error")["code"] == "ws_invalid_message"
            socket.send_text("{broken")
            assert _drain_until(socket, "error")["code"] == "ws_invalid_message"
            socket.send_json({"type": "nonsense"})
            frame = _drain_until(socket, "error")
            assert frame["code"] == "ws_unknown_message_type" and "nonsense" in frame["message"]
            socket.send_json({"type": "ping"})
            assert _drain_until(socket, "pong")


class TestSingleSessionLock:
    def test_a_second_tab_is_blocked_and_the_first_is_untouched(self, env):
        client, lobby = env["client"], env["lobby"]
        with lobby_socket(client, "Ann") as (first, welcome):
            message = _refused(client, account_header("Ann"), {"type": "auth"})
            assert (message["type"], message["reason"]) == ("disconnected", "parallel_session")
            first.send_json({"type": "ping"})
            assert _drain_until(first, "pong")
            assert lobby.player(welcome["player_id"]).connected
            assert manager.is_connected(welcome["player_id"])
        assert manager._pending == 0

    def test_the_block_does_not_apply_across_accounts(self, env):
        with lobby_socket(env["client"], "Ann"):
            with lobby_socket(env["client"], "Bob") as (_socket, welcome):
                assert welcome["name"] == "Bob"

    def test_a_tab_refresh_resumes_the_same_player_and_tab_id(self, env):
        client, lobby = env["client"], env["lobby"]
        gid, ann, bob = _seated_game(env)
        with lobby_socket(client, "Ann") as (_s, first):
            tab_id = first["tab_id"]
            assert first["player_id"] == ann  # the account's player, found by the account
        assert lobby.player(ann).connected is False  # seat held for the grace period
        with lobby_socket(client, "Ann", tab_id=tab_id) as (_s, second):
            assert second["player_id"] == ann
            assert second["reclaimed"] is True
            assert second["tab_id"] == tab_id
        assert lobby.player(ann).game_id == gid

    def test_a_refresh_before_the_server_saw_the_close_replaces_a_dead_socket(self, env, monkeypatch):
        # The old socket is still registered but never answers the liveness probe.
        monkeypatch.setattr(ws_module, "LIVENESS_PROBE_TIMEOUT_SECONDS", 0.15)
        client = env["client"]
        with lobby_socket(client, "Ann") as (old, first):
            tab_id = first["tab_id"]
            with lobby_socket(client, "Ann", tab_id=tab_id) as (_new, second):
                assert second["tab_id"] == tab_id
                assert second["player_id"] == first["player_id"]
            # the replaced socket was told why
            assert _drain_until(old, "disconnected")["reason"] == "replaced"

    def test_a_duplicated_tab_with_copied_session_storage_is_blocked(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (original, first):
            tab_id = first["tab_id"]
            with client.websocket_connect("/ws/lobby", headers=account_header("Ann")) as dup:
                dup.send_json({"type": "auth", "tab_id": tab_id})  # copied tab id, original alive
                answered = False
                while not answered:  # the live original answers the server's probe
                    message = original.receive_json()
                    if message.get("type") == ws_module.LIVENESS_MESSAGE_TYPE:
                        original.send_json({"type": ws_module.ALIVE_MESSAGE_TYPE})
                        answered = True
                refusal = dup.receive_json()
                assert (refusal["type"], refusal["reason"]) == ("disconnected", "parallel_session")
            original.send_json({"type": "ping"})
            assert _drain_until(original, "pong")

    def test_a_guessed_or_missing_tab_id_never_evicts(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (original, welcome):
            for guess in (None, "guess", "x" * 22, welcome["tab_id"][::-1]):
                message = _refused(
                    client, account_header("Ann"), {"type": "auth", **({"tab_id": guess} if guess else {})}
                )
                assert message["reason"] == "parallel_session"
            assert manager.is_connected(welcome["player_id"])
            original.send_json({"type": "ping"})
            assert _drain_until(original, "pong")

    def test_a_tab_id_of_another_account_is_not_honoured(self, env):
        client = env["client"]
        with lobby_socket(client, "Bob") as (_b, bob_welcome):
            with lobby_socket(client, "Ann") as (_a, ann_welcome):
                assert ann_welcome["tab_id"] != bob_welcome["tab_id"]
            with lobby_socket(client, "Ann", tab_id=bob_welcome["tab_id"]) as (_a, again):
                assert again["tab_id"] != bob_welcome["tab_id"]

    def test_a_crashed_tab_does_not_lock_the_account_out(self, env):
        client = env["client"]
        with lobby_socket(client, "Ann") as (old, first):
            manager.connection(first["player_id"]).last_seen -= ws_module.SOCKET_STALE_SECONDS + 1
            with lobby_socket(client, "Ann") as (_new, second):  # a fresh browser: no tab id at all
                assert second["player_id"] == first["player_id"]
            assert _drain_until(old, "disconnected")["reason"] == "replaced"

    def test_the_sweeper_drops_a_silent_socket_and_the_grace_rules_apply(self, env):
        client, lobby = env["client"], env["lobby"]
        gid, ann, _bob = _seated_game(env)
        with lobby_socket(client, "Ann") as (socket, welcome):
            manager.connection(ann).last_seen -= ws_module.SOCKET_STALE_SECONDS + 1
            _sweep(lobby, env["sessions"])
            assert _drain_until(socket, "disconnected")["reason"] == "stale"
        assert lobby.player(ann).connected is False
        assert lobby.player(ann).game_id == gid  # the seat is held, not conceded


@pytest.mark.real_auth
class TestSessionLifecycle:
    """Real accounts and sessions: cookie at upgrade, logout/expiry/disablement/deletion close sockets."""

    @pytest.fixture
    def stack(self, env):
        clock = {"now": 1_000_000.0}
        store = AccountStore(":memory:", clock=lambda: clock["now"])
        app.dependency_overrides[get_account_store] = lambda: store
        try:
            yield {**env, "store": store, "clock": clock}
        finally:
            app.dependency_overrides.pop(get_account_store, None)
            store.close()

    def _login(self, stack, name):
        account = stack["store"].create_account_unchecked(name, "!", "player")
        return account, self._new_session(stack, account)

    def _new_session(self, stack, account):
        token, session = stack["store"].create_session(account.player_uuid)
        client = TestClient(app)
        client.cookies.set(session_cookie_name(), token)
        return client, token, session

    def _open(self, client, tab_id=None, **auth):
        socket = client.websocket_connect("/ws/lobby")
        socket = socket.__enter__()
        socket.send_json({"type": "auth", **({"tab_id": tab_id} if tab_id else {}), **auth})
        return socket

    def test_a_socket_needs_a_real_session_cookie(self, stack):
        message = _refused(TestClient(app), {})
        assert message["reason"] == "unauthenticated"
        bogus = TestClient(app)
        bogus.cookies.set(session_cookie_name(), "not-a-session")
        assert _refused(bogus, {})["reason"] == "unauthenticated"

    def test_the_account_name_is_the_lobby_name_and_the_csrf_proof_is_checked(self, stack):
        account, (client, token, session) = self._login(stack, "Alice")
        socket = self._open(client, csrf_token=session.csrf_token)
        welcome = socket.receive_json()
        assert welcome["name"] == "Alice"
        assert stack["lobby"].player(welcome["player_id"]).player_uuid == account.player_uuid
        socket.__exit__(None, None, None)
        assert _refused(client, {}, {"type": "auth", "csrf_token": "forged"})["reason"] == "unauthenticated"

    def test_a_copied_tab_id_under_another_session_of_the_same_account_is_blocked(self, stack):
        account, (client1, _t1, _s1) = self._login(stack, "Alice")
        socket = self._open(client1)
        welcome = socket.receive_json()
        client2, _t2, _s2 = self._new_session(stack, account)  # the same account, a second login
        message = _refused(client2, {}, {"type": "auth", "tab_id": welcome["tab_id"]})
        assert message["reason"] == "parallel_session"
        socket.__exit__(None, None, None)

    def test_logout_closes_the_socket_and_relogin_within_grace_resumes_the_seat(self, stack):
        lobby = stack["lobby"]
        account, (client, token, _s) = self._login(stack, "Alice")
        _bob, (bob_client, _bt, _bs) = self._login(stack, "Bob")
        socket = self._open(client)
        alice = socket.receive_json()["player_id"]
        bob_socket = self._open(bob_client)
        bob = bob_socket.receive_json()["player_id"]
        # A table needs CSRF-less REST here: drive the lobby directly.
        game = lobby.create(alice)
        lobby.join(game.id, bob)
        assert lobby.player(alice).game_id == game.id

        stack["store"].revoke_session(token)  # what POST /api/auth/logout does
        _sweep(lobby, stack["sessions"], stack["store"])
        assert _drain_until(socket, "disconnected")["reason"] == "session_ended"
        assert lobby.player(alice).connected is False
        assert lobby.player(alice).game_id == game.id  # grace: the seat is held

        client2, _t, _s2 = self._new_session(stack, account)  # login again within the grace
        again = self._open(client2)
        welcome = again.receive_json()
        assert welcome["player_id"] == alice and welcome["reclaimed"] is True
        assert lobby.player(alice).connected
        again.__exit__(None, None, None)
        socket.__exit__(None, None, None)
        bob_socket.__exit__(None, None, None)

    def test_logout_all_expiry_disablement_and_deletion_each_close_the_socket(self, stack):
        lobby, store, clock = stack["lobby"], stack["store"], stack["clock"]
        cases = {}
        for name in ("Logout", "Expired", "Disabled", "Deleted"):
            account, (client, token, _s) = self._login(stack, name)
            cases[name] = (account, token, self._open(client))
            cases[name][2].receive_json()

        store.revoke_all_sessions(cases["Logout"][0].player_uuid)
        store.set_disabled(cases["Disabled"][0].player_uuid, True)
        store.delete_account(cases["Deleted"][0].player_uuid)
        _sweep(lobby, stack["sessions"], store)
        for name in ("Logout", "Disabled", "Deleted"):
            assert _drain_until(cases[name][2], "disconnected")["reason"] == "session_ended", name

        clock["now"] += 10 * 365 * 24 * 3600  # far past the idle and absolute lifetimes
        _sweep(lobby, stack["sessions"], store)
        assert _drain_until(cases["Expired"][2], "disconnected")["reason"] == "session_ended"
        assert manager._sockets == {}
        for _account, _token, socket in cases.values():
            socket.__exit__(None, None, None)

    def test_a_revoked_session_is_noticed_at_the_next_frame_without_a_sweep(self, stack):
        account, (client, token, _s) = self._login(stack, "Alice")
        socket = self._open(client)
        socket.receive_json()
        stack["store"].revoke_session(token)
        socket.send_json({"type": "ping"})
        assert _drain_until(socket, "disconnected")["reason"] == "session_ended"
        socket.__exit__(None, None, None)

    def test_a_live_socket_does_not_keep_an_idle_session_alive(self, stack):
        store, clock = stack["store"], stack["clock"]
        _account, (client, token, _s) = self._login(stack, "Alice")
        socket = self._open(client)
        socket.receive_json()
        before = store.list_sessions(_account.player_uuid)[0]["last_seen"]
        clock["now"] += 5
        _sweep(stack["lobby"], stack["sessions"], store)
        socket.send_json({"type": "ping"})
        assert _drain_until(socket, "pong")
        assert store.list_sessions(_account.player_uuid)[0]["last_seen"] == before
        socket.__exit__(None, None, None)

    def test_rest_actions_stop_with_the_session(self, stack):
        account, (client, token, session) = self._login(stack, "Alice")
        headers = {"X-CSRF-Token": session.csrf_token}
        assert client.post("/api/multiplayer/connect", headers=headers).status_code == 200
        stack["store"].revoke_session(token)
        assert client.post("/api/multiplayer/connect", headers=headers).status_code == 401
        assert client.get("/api/multiplayer/lobby").status_code == 401

    def test_two_accounts_see_only_their_own_hands(self, stack):
        # Hidden information is unchanged: each socket gets its own redacted view.
        from tests.api.test_api_multiplayer import _legal_deck

        lobby = stack["lobby"]
        _a, (ac, _at, asess) = self._login(stack, "Alice")
        _b, (bc, _bt, bsess) = self._login(stack, "Bob")
        deck = _legal_deck(stack["decks"])
        a_sock, b_sock = self._open(ac), self._open(bc)
        alice, bob = a_sock.receive_json()["player_id"], b_sock.receive_json()["player_id"]
        ah, bh = {"X-CSRF-Token": asess.csrf_token}, {"X-CSRF-Token": bsess.csrf_token}
        gid = ac.post("/api/multiplayer/games", json={"playerId": alice}, headers=ah).json()["game"]["id"]
        bc.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": bob}, headers=bh)
        for client, pid, headers in ((ac, alice, ah), (bc, bob, bh)):
            client.post(f"/api/multiplayer/games/{gid}/deck", json={"playerId": pid, "deckId": deck.id}, headers=headers)
        for client, pid, headers in ((ac, alice, ah), (bc, bob, bh)):
            client.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid}, headers=headers)
        assert ac.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": alice}, headers=ah).status_code == 200
        # Alice cannot name Bob's player over REST, and Bob's socket view hides Alice's hand.
        assert ac.get(f"/api/multiplayer/games/{gid}", params={"player_id": bob}).status_code == 403
        for _ in range(40):
            message = b_sock.receive_json()
            if message.get("type") == "game_update" and message.get("view"):
                players = {p["id"]: p for p in message["view"]["state"]["players"]}
                assert len(players[bob]["hand"]) == 7 and players[alice]["hand"] == []
                break
        else:
            raise AssertionError("no board arrived")
        a_sock.__exit__(None, None, None)
        b_sock.__exit__(None, None, None)
