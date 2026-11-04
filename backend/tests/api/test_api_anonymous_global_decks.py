"""PLR-18: global decks are open to everyone; anonymous sessions have their own owner proof.

`real_auth` clients: an anonymous browser (no login), two more anonymous browsers, and an account.
Covers the anonymous read/play matrix over every deck consumer and session route, the 401s that
must stay (writes, copies, favourites, multiplayer), anonymous-cookie isolation, cookie flags per
run mode, CSRF behaviour and the anonymous resource caps. Every store is a throwaway one.
"""

import json

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.api.auth import session_cookie_name
from mtg_analyzer.api.dependencies import (
    get_account_store,
    get_deck_database,
    get_dynamic_analysis_jobs,
    get_game_session_manager,
    get_lazy_card_loader,
    get_lobby,
)
from mtg_analyzer.api.viewer import ANON_COOKIE_LAN, ANON_COOKIE_ONLINE, anon_cookie_name
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.account_store import ROLE_PLAYER, AccountStore
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import (
    ANONYMOUS_OWNER_PREFIX,
    GOLDFISH,
    GameSession,
    GameSessionManager,
    build_goldfish_engine,
)
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.lobby import Lobby

pytestmark = pytest.mark.real_auth

MISSING = "00000000-0000-0000-0000-000000000000"
FOREST = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
COMMANDER = Card(
    id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
    is_creature=True, power=1, toughness=1, color_identity=set(),
)


class _Loader:
    _cards = {"Forest": FOREST, "Test Commander": COMMANDER}

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


class _FakeJobs:
    def __init__(self):
        self.started = []
        self.jobs = {}

    def start(self, library, commanders, **kw):
        self.started.append(kw.get("owner"))
        return "job-1"

    def get(self, job_id):
        return None


class _Client:
    """A browser: its own cookie jar; an account login adds the session cookie and CSRF header."""

    def __init__(self, csrf=None):
        self.http = TestClient(app)
        self.csrf = csrf

    def call(self, method, url, **kw):
        headers = dict(kw.pop("headers", {}))
        if self.csrf and method.upper() not in ("GET", "HEAD"):
            headers.setdefault("X-CSRF-Token", self.csrf)
        return self.http.request(method, url, headers=headers, **kw)

    def get(self, url, **kw):
        return self.call("GET", url, **kw)

    def post(self, url, **kw):
        return self.call("POST", url, **kw)

    def delete(self, url, **kw):
        return self.call("DELETE", url, **kw)

    @property
    def anon_cookie(self):
        return self.http.cookies.get(anon_cookie_name())


@pytest.fixture
def world(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    decks = DeckDatabase(tmp_path / "decks.db")
    sessions = GameSessionManager()
    lobby = Lobby()
    jobs = _FakeJobs()
    overrides = {
        get_account_store: lambda: accounts,
        get_deck_database: lambda: decks,
        get_game_session_manager: lambda: sessions,
        get_lobby: lambda: lobby,
        get_dynamic_analysis_jobs: lambda: jobs,
        get_lazy_card_loader: lambda: _Loader(),
    }
    app.dependency_overrides.update(overrides)

    def account(name):
        acct = accounts.create_account_unchecked(name, "!", ROLE_PLAYER)
        token, session = accounts.create_session(acct.player_uuid)
        client = _Client(session.csrf_token)
        client.http.cookies.set(session_cookie_name(), token)
        client.uuid = acct.player_uuid
        return client

    def deck(name, owner=None):
        d = Deck(name=name, commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
        (decks.save_global(d) if owner is None else decks.save_private(d, owner))
        return d

    alice = account("Alice")
    unassigned = Deck(name="Legacy", commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
    with decks._lock:  # a legacy row the operator migration has not classified yet
        decks._connection.execute(
            "INSERT INTO decks (id, name, created_at, data, scope, owner) VALUES (?, ?, ?, ?, 'unassigned', NULL)",
            (unassigned.id, unassigned.name, unassigned.created_at, json.dumps(unassigned.to_dict())),
        )
        decks._connection.commit()
    yield {
        "alice": alice, "account": account, "anon": _Client(), "anon2": _Client(),
        "decks": decks, "sessions": sessions, "lobby": lobby, "jobs": jobs,
        "gdeck": deck("Global"), "adeck": deck("Alice's", alice.uuid), "legacy": unassigned,
    }
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


# -- the anonymous read matrix ------------------------------------------------------------------


def test_anonymous_lists_and_reads_global_decks_only(world):
    anon = world["anon"]
    assert [d["name"] for d in anon.get("/api/decks").json()] == ["Global"]
    assert all("owner" not in d for d in anon.get("/api/decks").json())
    for suffix in ("", "/validation", "/coverage"):
        assert anon.get(f"/api/decks/{world['gdeck'].id}{suffix}").status_code == 200, suffix
    assert anon.anon_cookie is None  # reads never issue an anonymous id


@pytest.mark.parametrize("suffix", ["", "/validation", "/coverage"])
def test_private_and_unassigned_ids_look_exactly_like_missing_ones(world, suffix):
    anon = world["anon"]
    missing = anon.get(f"/api/decks/{MISSING}{suffix}")
    for deck in (world["adeck"], world["legacy"]):
        got = anon.get(f"/api/decks/{deck.id}{suffix}")
        assert got.status_code == missing.status_code == 404
        assert got.text.replace(deck.id, "X") == missing.text.replace(MISSING, "X")


def test_cached_validation_and_coverage_are_served_for_global_decks_only(world):
    decks = world["decks"]
    decks.store_derived(world["gdeck"], {"validationResult": {"isLegal": True, "cached": 1}})
    decks.store_derived(world["adeck"], {"validationResult": {"isLegal": True, "secret": 1}})
    assert world["anon"].get(f"/api/decks/{world['gdeck'].id}/validation").json()["cached"] == 1
    assert world["anon"].get(f"/api/decks/{world['adeck'].id}/validation").status_code == 404


def test_stats_and_cards_listing_cover_global_decks_for_anonymous_callers(world):
    assert world["anon"].get("/api/stats").json()["decks"] == 1
    assert world["anon"].get("/api/cards?scope=decks").status_code == 200


# -- what stays login-only ----------------------------------------------------------------------


def test_anonymous_writes_copies_favourites_and_multiplayer_are_401(world):
    anon, gid = world["anon"], world["gdeck"].id
    refused = [
        anon.post("/api/decks/save", json={"name": "x"}),
        anon.post("/api/decks/save", json={"id": gid, "name": "x"}),
        anon.delete(f"/api/decks/{gid}"),
        anon.post(f"/api/decks/{gid}/copy"),
        anon.get("/api/me/favorite-decks"),
        anon.get("/api/me/sleeves"),
        anon.post("/api/multiplayer/connect"),
        anon.get("/api/multiplayer/lobby"),
        anon.post("/api/multiplayer/games", json={"playerId": "x"}),
    ]
    assert [r.status_code for r in refused if r.status_code != 404] == [401] * len(
        [r for r in refused if r.status_code != 404]
    )
    assert world["decks"].get_global(gid).name == "Global"
    assert world["decks"].count_private(world["alice"].uuid) == 1
    assert anon.anon_cookie is None  # a refused write does not issue an anonymous id


# -- the anonymous play matrix ------------------------------------------------------------------


def _consumers(deck_id):
    return [
        ("POST", "/api/game/goldfish", {"deckId": deck_id}),
        ("POST", "/api/game/deck-tokens", {"deckId": deck_id}),
        ("POST", "/api/archetypes/analyze", {"deckId": deck_id}),
        ("POST", "/api/analysis/dynamic", {"deckId": deck_id, "numMatches": 1}),
        ("POST", "/api/solo/start", {"deckId": deck_id, "opponents": [{"kind": "goldfish", "deckId": deck_id}]}),
    ]


@pytest.mark.parametrize("index", range(5))
def test_every_deck_consumer_accepts_a_global_deck_anonymously(world, index):
    method, url, body = _consumers(world["gdeck"].id)[index]
    assert world["anon"].call(method, url, json=body).status_code in (200, 422), url


@pytest.mark.parametrize("index", range(5))
def test_every_deck_consumer_treats_private_and_unassigned_as_missing(world, index):
    method, url, missing_body = _consumers(MISSING)[index]
    missing = world["anon"].call(method, url, json=missing_body)
    for deck in (world["adeck"], world["legacy"]):
        _m, _u, body = _consumers(deck.id)[index]
        got = world["anon"].call(method, url, json=body)
        assert got.status_code == missing.status_code in (404, 422)
        assert got.text.replace(deck.id, "X") == missing.text.replace(MISSING, "X")


def test_an_anonymous_goldfish_start_works_and_a_text_deck_too(world):
    anon = world["anon"]
    started = anon.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
    assert started.status_code == 200, started.text
    pasted = anon.post("/api/game/goldfish", json={
        "commanderText": "1 Test Commander", "mainboardText": "99 Forest"})
    assert pasted.status_code == 200, pasted.text


def test_an_anonymous_replay_start_works(world):
    assert world["anon"].post("/api/game/replay", json={"numPlayers": 1}).status_code == 200


def test_an_anonymous_solo_host_can_pick_only_global_bot_decks(world):
    anon = world["anon"]
    body = {"deckId": world["gdeck"].id, "opponents": [{"kind": "goldfish", "deckId": world["adeck"].id}]}
    refused = anon.post("/api/solo/start", json=body)
    assert refused.status_code == 422 and refused.json()["detail"]["errors"] == ["Deck existiert nicht mehr."]
    body["opponents"][0]["deckId"] = world["gdeck"].id
    assert anon.post("/api/solo/start", json=body).status_code == 200


def test_the_account_still_reads_private_decks_and_gets_no_anonymous_cookie(world):
    alice = world["alice"]
    assert sorted(d["name"] for d in alice.get("/api/decks").json()) == ["Alice's", "Global"]
    assert alice.post("/api/game/goldfish", json={"deckId": world["adeck"].id}).status_code == 200
    assert alice.anon_cookie is None


def test_dynamic_analysis_jobs_record_the_anonymous_owner(world):
    anon = world["anon"]
    assert anon.post("/api/analysis/dynamic", json={"deckId": world["gdeck"].id, "numMatches": 1}).status_code == 200
    owner = world["jobs"].started[0]
    assert owner.startswith(ANONYMOUS_OWNER_PREFIX) and anon.anon_cookie.split(".")[0] not in owner


# -- anonymous owner proof and isolation --------------------------------------------------------


def _start(client, world, flavor):
    if flavor == "goldfish":
        r = client.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
        return "game", r.json()["id"] if "id" in r.json() else r.json()["session_id"]
    if flavor == "replay":
        r = client.post("/api/game/replay", json={"numPlayers": 1})
        return "game", r.json()["id"] if "id" in r.json() else r.json()["session_id"]
    r = client.post("/api/solo/start", json={
        "deckId": world["gdeck"].id, "opponents": [{"kind": "goldfish", "deckId": world["gdeck"].id}]})
    return "solo", r.json()["id"] if "id" in r.json() else r.json()["session_id"]


def _routes(prefix, sid):
    base = f"/api/{prefix}/{sid}"
    return [
        ("GET", base, None),
        ("POST", f"{base}/action", {"type": "noop"}),
        ("POST", f"{base}/restart", {}),
        ("POST", f"{base}/ui-draft", {"draft": None}),
        ("GET", f"{base}/replay-export", None),
        ("DELETE", base, None),
    ] + ([("POST", f"{base}/rewind", {})] if prefix == "game" else [("POST", f"{base}/concede", {})])


@pytest.mark.parametrize("flavor", ["goldfish", "replay", "solo"])
def test_an_anonymous_session_is_reachable_only_with_its_own_cookie(world, flavor):
    first, second, alice = world["anon"], world["anon2"], world["alice"]
    prefix, sid = _start(first, world, flavor)
    owner = world["sessions"].get(sid).owner
    assert owner.startswith(ANONYMOUS_OWNER_PREFIX) and owner != ANONYMOUS_OWNER_PREFIX
    assert first.anon_cookie.split(".")[0] not in owner  # only a digest is kept server side
    cookieless = _Client()
    for method, url, body in _routes(prefix, sid):
        miss = url.replace(sid, MISSING)
        for stranger in (second, alice, cookieless):
            denied = stranger.call(method, url, json=body)
            assert denied.status_code == 404, (stranger, url)
            assert denied.text.replace(sid, "X") == stranger.call(method, miss, json=body).text.replace(MISSING, "X")
    assert first.get(f"/api/{prefix}/{sid}").status_code == 200
    assert first.delete(f"/api/{prefix}/{sid}").status_code == 200


def test_a_second_anonymous_browser_cannot_act_on_the_first_ones_session(world):
    first, second = world["anon"], world["anon2"]
    _prefix, sid = _start(first, world, "goldfish")
    second.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})  # it now holds its own id
    assert second.anon_cookie and second.anon_cookie != first.anon_cookie
    assert second.post(f"/api/game/{sid}/action", json={"type": "noop"}).status_code == 404
    assert second.delete(f"/api/game/{sid}").status_code == 404
    assert world["sessions"].get(sid) is not None


def test_account_sessions_are_unreachable_with_an_anonymous_cookie_and_vice_versa(world):
    alice, anon = world["alice"], world["anon"]
    _p, account_sid = _start(alice, world, "goldfish")
    _p, anon_sid = _start(anon, world, "goldfish")
    assert world["sessions"].get(account_sid).owner == alice.uuid
    assert anon.get(f"/api/game/{account_sid}").status_code == 404
    assert alice.get(f"/api/game/{anon_sid}").status_code == 404
    # Logged in *and* holding an anonymous cookie: the account never reaches its anonymous past.
    alice.http.cookies.set(anon_cookie_name(), anon.anon_cookie)
    assert alice.get(f"/api/game/{anon_sid}").status_code == 404
    assert alice.get(f"/api/game/{account_sid}").status_code == 200


def test_lobby_and_ownerless_sessions_are_never_reachable(world):
    session = GameSession(build_goldfish_engine([FOREST] * 3), mode=GOLDFISH)
    world["sessions"]._sessions[session.id] = session
    anon = world["anon"]
    anon.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})  # holds a valid anonymous id
    assert anon.get(f"/api/game/{session.id}").status_code == 404
    with pytest.raises(KeyError):
        world["sessions"].get_owned(session.id, "")
    with pytest.raises(KeyError):
        world["sessions"].get_owned(session.id, ANONYMOUS_OWNER_PREFIX)


def test_a_forged_or_tampered_anonymous_cookie_is_ignored(world):
    anon = world["anon"]
    _p, sid = _start(anon, world, "goldfish")
    cookie = anon.anon_cookie
    anon_id, _dot, mac = cookie.partition(".")
    for forged in (anon_id, f"{anon_id}.{'0' * 64}", f"x{anon_id}.{mac}", "", "a.b"):
        stranger = _Client()
        stranger.http.cookies.set(anon_cookie_name(), forged)
        assert stranger.get(f"/api/game/{sid}").status_code == 404, forged
    # A forged cookie on a play route is replaced by a fresh server-issued id, not adopted.
    stranger = _Client()
    stranger.http.cookies.set(anon_cookie_name(), f"{anon_id}.{'0' * 64}")
    issued = stranger.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
    assert f"{anon_id}.{'0' * 64}" not in _set_cookie_header(issued, ANON_COOKIE_LAN)
    assert ANON_COOKIE_LAN in issued.headers["set-cookie"]


def test_an_anonymous_visitor_keeps_one_id_across_starts(world):
    anon = world["anon"]
    anon.post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
    first = anon.anon_cookie
    anon.post("/api/game/replay", json={"numPlayers": 1})
    assert anon.anon_cookie == first
    owners = {s.owner for s in world["sessions"]._sessions.values()}
    assert len(owners) == 1


# -- cookie flags and CSRF ----------------------------------------------------------------------


def _set_cookie_header(response, name):
    return next(v for k, v in response.headers.multi_items() if k == "set-cookie" and v.startswith(f"{name}="))


def test_lan_anonymous_cookie_flags(world, monkeypatch):
    monkeypatch.setattr(config, "RUN_MODE", "lan")
    r = world["anon"].post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
    header = _set_cookie_header(r, ANON_COOKIE_LAN).lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header
    assert "secure" not in header and "domain" not in header


def test_online_anonymous_cookie_is_host_prefixed_and_secure(world, monkeypatch):
    monkeypatch.setattr(config, "RUN_MODE", "online")
    r = world["anon"].post("/api/game/goldfish", json={"deckId": world["gdeck"].id})
    header = _set_cookie_header(r, ANON_COOKIE_ONLINE).lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header and "secure" in header
    assert "domain" not in header  # __Host- requires a host-only cookie


def test_anonymous_unsafe_requests_need_no_csrf_token_but_still_pass_the_origin_checks(world):
    anon = world["anon"]
    body = {"deckId": world["gdeck"].id}
    assert anon.post("/api/game/goldfish", json=body).status_code == 200  # no X-CSRF-Token: none exists
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
        denied = anon.post("/api/game/goldfish", json=body, headers=headers)
        assert denied.status_code == 403, headers
    same = anon.post("/api/game/goldfish", json=body, headers={"Sec-Fetch-Site": "same-origin"})
    assert same.status_code == 200


def test_an_account_still_needs_its_csrf_token_even_with_an_anonymous_cookie(world):
    alice = world["alice"]
    alice.http.cookies.set(anon_cookie_name(), "whatever")
    alice.csrf = None
    assert alice.post("/api/game/goldfish", json={"deckId": world["gdeck"].id}).status_code == 403
    alice.csrf = "wrong"
    assert alice.post("/api/game/goldfish", json={"deckId": world["gdeck"].id}).status_code == 403


# -- resource caps ------------------------------------------------------------------------------


def _anon_session(manager, owner):
    session = GameSession(build_goldfish_engine([FOREST] * 3), mode=GOLDFISH)
    session.owner = owner
    manager._register(session)
    return session


def test_one_anonymous_id_cannot_hold_more_than_the_per_owner_cap(monkeypatch):
    monkeypatch.setattr(config, "ANON_SESSION_MAX_PER_OWNER", 2)
    clock = iter(range(1000))
    manager = GameSessionManager(clock=lambda: next(clock))
    mine = [_anon_session(manager, "anon:a") for _ in range(4)]
    other = _anon_session(manager, "anon:b")
    alive = {s.id for s in manager._sessions.values()}
    assert {mine[2].id, mine[3].id, other.id} == alive  # oldest of "anon:a" went first


def test_rotating_anonymous_ids_cannot_exceed_the_total_cap_or_evict_accounts(monkeypatch):
    monkeypatch.setattr(config, "ANON_SESSION_MAX_TOTAL", 3)
    clock = iter(range(1000))
    manager = GameSessionManager(clock=lambda: next(clock))
    account = _anon_session(manager, "player-uuid-1")
    for i in range(10):
        _anon_session(manager, f"anon:{i}")
    anon = [s for s in manager._sessions.values() if s.owner.startswith(ANONYMOUS_OWNER_PREFIX)]
    assert len(anon) == 3 and account.id in manager._sessions


def test_the_global_cap_evicts_anonymous_sessions_before_accounts(monkeypatch):
    clock = iter(range(1000))
    manager = GameSessionManager(max_sessions=3, clock=lambda: next(clock))
    account = _anon_session(manager, "player-uuid-1")  # the oldest of all
    anon = _anon_session(manager, "anon:a")
    _anon_session(manager, "player-uuid-2")
    _anon_session(manager, "player-uuid-3")
    assert account.id in manager._sessions and anon.id not in manager._sessions
