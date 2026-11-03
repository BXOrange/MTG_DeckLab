"""PLR-9b: deck scope/owner authorization across every deck consumer and private session route.

Two players and an admin with real sessions (`real_auth`): global decks are readable by every
player, private decks only by their owner, foreign private ids look exactly like missing ones,
and a session id never bypasses the deck scoping it was started under.
"""

import pytest
from fastapi.testclient import TestClient

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
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.account_store import ROLE_ADMIN, ROLE_PLAYER, AccountStore
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.dynamic_analysis import DynamicAnalysisJob, DynamicAnalysisJobs
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.lobby import Lobby
from tests.mp_secret_client import SecretInjectingClient

pytestmark = pytest.mark.real_auth

MISSING = "00000000-0000-0000-0000-000000000000"


class _Loader:
    def __init__(self):
        self._cards = {
            "Forest": Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True),
            "Test Commander": Card(
                id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
                is_creature=True, power=1, toughness=1, color_identity=set(),
            ),
        }

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


class _Actor:
    """A client bound to one account's session (cookie plus the session CSRF header)."""

    def __init__(self, client, uuid, csrf):
        self.client, self.uuid, self.csrf = client, uuid, csrf

    def call(self, method, url, **kw):
        headers = dict(kw.pop("headers", {}))
        if method.upper() not in ("GET", "HEAD"):
            headers["X-CSRF-Token"] = self.csrf
        return self.client.request(method, url, headers=headers, **kw)

    def get(self, url, **kw):
        return self.call("GET", url, **kw)

    def post(self, url, **kw):
        return self.call("POST", url, **kw)

    def delete(self, url, **kw):
        return self.call("DELETE", url, **kw)


class _Anonymous(_Actor):
    def __init__(self, client):
        super().__init__(client, None, "")


class _FakeJobs:
    def __init__(self):
        self.started = []

    def start(self, library, commanders, **kw):
        self.started.append(kw.get("owner"))
        return "job-1"

    def get(self, job_id):
        return None


@pytest.fixture
def world(tmp_path):
    accounts = AccountStore(tmp_path / "accounts.db")
    decks = DeckDatabase(tmp_path / "decks.db")
    sessions = GameSessionManager()
    lobby = Lobby()
    jobs = DynamicAnalysisJobs(num_workers=1)
    fake_jobs = _FakeJobs()
    loader = _Loader()
    overrides = {
        get_account_store: lambda: accounts,
        get_deck_database: lambda: decks,
        get_game_session_manager: lambda: sessions,
        get_lobby: lambda: lobby,
        get_dynamic_analysis_jobs: lambda: fake_jobs,
        get_lazy_card_loader: lambda: loader,
    }
    app.dependency_overrides.update(overrides)

    def actor(name, role=ROLE_PLAYER):
        account = accounts.create_account_unchecked(name, "!", role)
        token, session = accounts.create_session(account.player_uuid)
        client = SecretInjectingClient(app, lobby=lobby)
        client.cookies.set(session_cookie_name(), token)
        return _Actor(client, account.player_uuid, session.csrf_token)

    alice, bob, admin = actor("Alice"), actor("Bob"), actor("Boss", ROLE_ADMIN)

    def deck(name, owner=None):
        d = Deck(name=name, commander_text="1 Test Commander\n", mainboard_text="99 Forest\n")
        (decks.save_global(d) if owner is None else decks.save_private(d, owner))
        return d

    yield {
        "alice": alice, "bob": bob, "admin": admin, "anon": _Anonymous(TestClient(app)),
        "decks": decks, "sessions": sessions, "lobby": lobby, "jobs": jobs, "fake_jobs": fake_jobs,
        "deck": deck, "gdeck": deck("Global"), "adeck": deck("Alice's", alice.uuid),
        "bdeck": deck("Bob's", bob.uuid),
    }
    for dep in overrides:
        app.dependency_overrides.pop(dep, None)


# -- saved-deck routes ------------------------------------------------------------------------


def test_players_read_global_and_own_private_only(world):
    alice, bob = world["alice"], world["bob"]
    names = lambda r: sorted(d["name"] for d in r.json())
    assert names(alice.get("/api/decks")) == ["Alice's", "Global"]
    assert names(bob.get("/api/decks")) == ["Bob's", "Global"]
    scopes = {d["name"]: d["scope"] for d in alice.get("/api/decks").json()}
    assert scopes == {"Alice's": "private", "Global": "global"}
    assert all("owner" not in d for d in alice.get("/api/decks").json())


@pytest.mark.parametrize("suffix", ["", "/validation", "/coverage"])
def test_foreign_private_and_missing_ids_are_the_same_404(world, suffix):
    alice = world["alice"]
    foreign = alice.get(f"/api/decks/{world['bdeck'].id}{suffix}")
    missing = alice.get(f"/api/decks/{MISSING}{suffix}")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"].replace(world["bdeck"].id, "X") == missing.json()["detail"].replace(MISSING, "X")
    assert alice.get(f"/api/decks/{world['adeck'].id}{suffix}").status_code == 200
    assert alice.get(f"/api/decks/{world['gdeck'].id}{suffix}").status_code == 200


def test_foreign_private_deck_cache_is_never_served_or_computed(world):
    bdeck, decks = world["bdeck"], world["decks"]
    decks.store_derived(bdeck, {"validationResult": {"isLegal": True, "secret": 1}})
    assert world["alice"].get(f"/api/decks/{bdeck.id}/validation").status_code == 404
    assert world["bob"].get(f"/api/decks/{bdeck.id}/validation").json()["secret"] == 1


def test_unauthenticated_and_admin_requests_are_401(world):
    for who in (world["anon"], world["admin"]):
        assert who.get("/api/decks").status_code == 401
        assert who.get(f"/api/decks/{world['gdeck'].id}").status_code == 401
        assert who.post("/api/decks/save", json={"name": "x"}).status_code == 401
        assert who.delete(f"/api/decks/{world['gdeck'].id}").status_code == 401
        assert who.post(f"/api/decks/{world['gdeck'].id}/copy").status_code == 401
    assert world["decks"].get_deck(world["gdeck"].id, world["alice"].uuid) is not None


def test_create_is_always_private_and_owned_by_the_verified_player(world):
    alice, bob = world["alice"], world["bob"]
    body = {"name": "New", "mainboardText": "99 Forest", "owner": bob.uuid, "scope": "global"}
    created = alice.post("/api/decks/save", json=body)
    assert created.status_code == 200 and created.json()["scope"] == "private"
    row = world["decks"].get_deck(created.json()["id"], alice.uuid)
    assert row.owner == alice.uuid and row.scope == "private"
    assert world["decks"].get_deck(created.json()["id"], bob.uuid) is None


def test_update_and_delete_need_the_private_owner(world):
    alice, bob = world["alice"], world["bob"]
    url = {"id": world["adeck"].id, "name": "Hijack"}
    assert bob.post("/api/decks/save", json=url).status_code == 404
    assert world["decks"].get_deck(world["adeck"].id, alice.uuid).name == "Alice's"
    assert bob.delete(f"/api/decks/{world['adeck'].id}").status_code == 404
    assert world["decks"].get_deck(world["adeck"].id, alice.uuid) is not None
    assert alice.post("/api/decks/save", json={**url, "name": "Renamed"}).json()["name"] == "Renamed"
    assert alice.delete(f"/api/decks/{world['adeck'].id}").status_code == 200
    assert alice.delete(f"/api/decks/{world['adeck'].id}").status_code == 404


def test_saving_with_an_unknown_id_is_404_not_a_client_chosen_create(world):
    assert world["alice"].post("/api/decks/save", json={"id": MISSING, "name": "x"}).status_code == 404
    assert world["decks"].get_deck(MISSING, world["alice"].uuid) is None


def test_global_decks_cannot_be_written_through_player_endpoints(world):
    alice, gid = world["alice"], world["gdeck"].id
    assert alice.post("/api/decks/save", json={"id": gid, "name": "Mine now"}).status_code == 403
    assert alice.delete(f"/api/decks/{gid}").status_code == 403
    assert world["decks"].get_deck(gid, alice.uuid).name == "Global"
    assert world["decks"].get_deck(gid, alice.uuid).scope == "global"


def test_copy_of_a_global_deck_is_a_new_private_id_and_leaves_the_source(world):
    alice, bob, gid = world["alice"], world["bob"], world["gdeck"].id
    copy = alice.post(f"/api/decks/{gid}/copy")
    assert copy.status_code == 200
    body = copy.json()
    assert body["id"] != gid and body["scope"] == "private" and body["mainboardText"] == "99 Forest\n"
    assert world["decks"].get_deck(body["id"], bob.uuid) is None
    assert world["decks"].get_deck(gid, alice.uuid).scope == "global"
    assert bob.post(f"/api/decks/{world['adeck'].id}/copy").status_code == 404


def test_derived_cache_on_a_global_deck_is_written_and_content_is_untouched(world):
    gid = world["gdeck"].id
    first = world["alice"].get(f"/api/decks/{gid}").json()
    assert first["colorIdentity"] == []
    stored = world["decks"].get_deck(gid, world["bob"].uuid)
    assert stored.color_identity == [] and stored.name == "Global" and stored.scope == "global"


# -- other deck consumers -----------------------------------------------------------------------


def _consumers(deck_id):
    """(method, url, body) for every route that takes a saved deck id."""
    return [
        ("POST", "/api/game/goldfish", {"deckId": deck_id}),
        ("POST", "/api/game/deck-tokens", {"deckId": deck_id}),
        ("POST", "/api/archetypes/analyze", {"deckId": deck_id}),
        ("POST", "/api/analysis/dynamic", {"deckId": deck_id, "numMatches": 1}),
        ("POST", "/api/solo/start", {"deckId": deck_id, "opponents": [{"kind": "goldfish", "deckId": deck_id}]}),
    ]


@pytest.mark.parametrize("index", range(5))
def test_every_deck_consumer_refuses_foreign_private_decks_before_computing(world, index):
    method, url, body = _consumers(world["bdeck"].id)[index]
    loader_calls = []
    original = _Loader.load_cards
    _Loader.load_cards = lambda self, names: (loader_calls.append(names), original(self, names))[1]
    try:
        refused = world["alice"].call(method, url, json=body)
    finally:
        _Loader.load_cards = original
    # Same answer as for an id that does not exist at all (solo reports it as an unplayable deck).
    method, url, missing_body = _consumers(MISSING)[index]
    missing = world["alice"].call(method, url, json=missing_body)
    assert refused.status_code == missing.status_code in (404, 422) and loader_calls == []
    assert refused.text.replace(world["bdeck"].id, "X") == missing.text.replace(MISSING, "X")
    assert world["bob"].call(method, url, json=body).status_code in (200, 422)
    assert world["bob"].call(method, url, json=body).text != refused.text
    assert world["anon"].call(method, url, json=body).status_code == 401


@pytest.mark.parametrize("index", range(5))
def test_every_deck_consumer_accepts_global_and_own_private(world, index):
    for deck in (world["gdeck"], world["adeck"]):
        method, url, body = _consumers(deck.id)[index]
        assert world["alice"].call(method, url, json=body).status_code in (200, 422), url


def test_a_solo_bot_deck_must_be_readable_by_the_host(world):
    body = {"deckId": world["adeck"].id, "opponents": [{"kind": "goldfish", "deckId": world["bdeck"].id}]}
    refused = world["alice"].post("/api/solo/start", json=body)
    assert refused.status_code == 422 and refused.json()["detail"]["errors"] == ["Deck existiert nicht mehr."]
    assert world["alice"].post("/api/solo/start", json={
        **body, "opponents": [{"kind": "goldfish", "deckId": world["gdeck"].id}]
    }).status_code == 200


def test_cards_listing_and_stats_count_only_readable_decks(world):
    assert world["anon"].get("/api/cards?scope=decks").status_code == 401
    assert world["alice"].get("/api/cards?scope=decks").status_code == 200
    assert world["anon"].get("/api/stats").json()["decks"] == 1  # the global deck only
    assert world["alice"].get("/api/stats").json()["decks"] == 2
    assert world["admin"].get("/api/stats").json()["decks"] == 1  # admins read no private decks


def test_dynamic_analysis_jobs_belong_to_their_starter(world):
    alice = world["alice"]
    body = {"deckId": world["adeck"].id, "numMatches": 1}
    assert alice.post("/api/analysis/dynamic", json=body).status_code == 200
    assert world["fake_jobs"].started == [alice.uuid]
    jobs = DynamicAnalysisJobs(num_workers=1)
    jobs._jobs["j"] = DynamicAnalysisJob(id="j", owner=alice.uuid)
    app.dependency_overrides[get_dynamic_analysis_jobs] = lambda: jobs
    assert alice.get("/api/analysis/dynamic/j").status_code == 200
    assert world["bob"].get("/api/analysis/dynamic/j").status_code == 404
    assert world["anon"].get("/api/analysis/dynamic/j").status_code == 401


# -- private sessions ---------------------------------------------------------------------------


def _session_routes(prefix, sid):
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
def test_session_routes_are_owner_only(world, flavor):
    alice, bob = world["alice"], world["bob"]
    if flavor == "goldfish":
        started = alice.post("/api/game/goldfish", json={"deckId": world["adeck"].id})
        prefix = "game"
    elif flavor == "replay":
        started = alice.post("/api/game/replay", json={"numPlayers": 1})
        prefix = "game"
    else:
        started = alice.post("/api/solo/start", json={
            "deckId": world["adeck"].id, "opponents": [{"kind": "goldfish", "deckId": world["gdeck"].id}]})
        prefix = "solo"
    assert started.status_code == 200, started.text
    sid = started.json()["session_id"] if "session_id" in started.json() else started.json()["id"]
    assert world["sessions"].get(sid).owner == alice.uuid
    unknown = [(m, u.replace(sid, MISSING), b) for m, u, b in _session_routes(prefix, sid)]
    for (method, url, body), (_, miss_url, _b) in zip(_session_routes(prefix, sid), unknown):
        foreign = bob.call(method, url, json=body)
        missing = bob.call(method, miss_url, json=body)
        assert foreign.status_code == missing.status_code == 404, url
        assert world["anon"].call(method, url, json=body).status_code == 401, url
        assert world["admin"].call(method, url, json=body).status_code == 401, url
    assert alice.get(f"/api/{prefix}/{sid}").status_code == 200
    assert alice.delete(f"/api/{prefix}/{sid}").status_code == 200


def test_a_foreign_session_poll_does_not_keep_the_session_alive(world):
    started = world["alice"].post("/api/game/goldfish", json={"deckId": world["adeck"].id}).json()
    sid = started["session_id"] if "session_id" in started else started["id"]
    before = world["sessions"]._last_access[sid]
    world["bob"].get(f"/api/game/{sid}")
    assert world["sessions"]._last_access[sid] == before


def test_ownerless_sessions_are_unreachable_from_the_player_routes(world):
    from mtg_analyzer.services.game_session import GOLDFISH, GameSession, build_goldfish_engine

    session = GameSession(build_goldfish_engine([Card(id="F", name="Forest", type_line="Land", is_land=True)] * 3),
                          mode=GOLDFISH)
    world["sessions"]._sessions[session.id] = session
    assert world["alice"].get(f"/api/game/{session.id}").status_code == 404


# -- multiplayer snapshots ----------------------------------------------------------------------


def _table(world):
    alice, bob = world["alice"], world["bob"]
    ann = alice.post("/api/multiplayer/connect", json={"name": "Ann"}).json()["player"]["id"]
    ben = bob.post("/api/multiplayer/connect", json={"name": "Ben"}).json()["player"]["id"]
    gid = alice.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
    bob.post(f"/api/multiplayer/games/{gid}/join", json={"playerId": ben})
    return gid, ann, ben


def test_a_seat_deck_pick_needs_read_access_and_start_uses_the_snapshot(world):
    alice, bob = world["alice"], world["bob"]
    gid, ann, ben = _table(world)
    pick = lambda who, pid, deck: who.post(
        f"/api/multiplayer/games/{gid}/deck", json={"playerId": pid, "deckId": deck.id}
    )
    assert pick(bob, ben, world["adeck"]).status_code == 404  # Alice's private deck
    assert pick(alice, ann, world["bdeck"]).status_code == 404
    assert pick(alice, ann, world["adeck"]).status_code == 200
    assert pick(bob, ben, world["bdeck"]).status_code == 200
    for who, pid in ((alice, ann), (bob, ben)):
        who.post(f"/api/multiplayer/games/{gid}/ready", json={"playerId": pid})
    seats = world["lobby"].game(gid).seats
    assert all(seat.deck_snapshot for seat in seats)
    assert "deck_snapshot" not in seats[0].to_dict()
    # Owners delete their decks after picking: the table still starts from the snapshots.
    assert alice.delete(f"/api/decks/{world['adeck'].id}").status_code == 200
    assert bob.delete(f"/api/decks/{world['bdeck'].id}").status_code == 200
    started = alice.post(f"/api/multiplayer/games/{gid}/start", json={"playerId": ann})
    assert started.status_code == 200, started.text


def test_a_host_picks_a_bot_seat_deck_only_from_what_the_host_can_read(world):
    alice = world["alice"]
    ann = alice.post("/api/multiplayer/connect", json={"name": "Ann"}).json()["player"]["id"]
    gid = alice.post("/api/multiplayer/games", json={"playerId": ann}).json()["game"]["id"]
    bots = alice.post(f"/api/multiplayer/games/{gid}/bots", json={"playerId": ann, "kind": "goldfish"})
    seat_id = bots.json()["game"]["seats"][-1]["player_id"]
    pick = lambda deck: alice.post(f"/api/multiplayer/games/{gid}/deck", json={
        "playerId": ann, "deckId": deck.id, "seatId": seat_id})
    assert pick(world["bdeck"]).status_code == 404
    assert pick(world["gdeck"]).status_code == 200
