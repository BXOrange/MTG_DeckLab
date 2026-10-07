"""Rooms through the session layer (MEC-111): the wire view, the unlock special action, Replay import/export and the editor."""

from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_deck_database, get_game_session_manager, get_lazy_card_loader
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult
from mtg_analyzer.services.replay import blank_replay, build_replay_engine, serialize_replay

ROOM = "Grand Entryway // Elegant Rotunda"  # {1}{W} Glimmer token / {2}{W} +1/+1 counters


class _Loader:
    def __init__(self):
        db = CardDatabase(DB_PATH)
        self._cards = {ROOM: db.get_card(ROOM), "Plains": db.get_card("Plains")}

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


def _setup():
    manager = GameSessionManager()
    deck_db = DeckDatabase()
    app.dependency_overrides[get_game_session_manager] = lambda: manager
    app.dependency_overrides[get_deck_database] = lambda: deck_db
    app.dependency_overrides[get_lazy_card_loader] = lambda: _Loader()


def _teardown():
    for dep in (get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _room(view):
    return next(o for o in view["state"]["battlefield"] if o["name"] == ROOM)


class TestRoomsReplay:
    def teardown_method(self):
        _teardown()

    def test_descriptor_round_trip_keeps_the_unlocked_doors_and_their_abilities(self):
        desc = blank_replay(1)
        desc["battlefield"].append({"name": ROOM, "owner_id": "p1", "controller_id": "p1", "unlocked_doors": ["right"]})
        engine = build_replay_engine(desc, _Loader())
        room = engine.state.battlefield[0]
        assert room.unlocked_doors == {"right"}
        assert room.triggered_abilities and all(a.door == "right" for a in room.triggered_abilities)
        exported = serialize_replay(engine.state)
        assert exported["battlefield"][0]["unlocked_doors"] == ["right"]

    def test_the_editor_sets_doors_directly_and_the_view_shows_them(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        view = client.post(f"/api/game/{sid}/action", json={
            "type": "edit_add_object", "zone": "battlefield", "owner_id": "p1", "name": ROOM}).json()
        room = _room(view)
        assert [(d["door"], d["unlocked"]) for d in room["room_doors"]] == [("left", False), ("right", False)]
        view = client.post(f"/api/game/{sid}/action", json={
            "type": "edit_set_doors", "instance_id": room["instance_id"], "doors": ["left"]}).json()
        doors = {d["door"]: d for d in _room(view)["room_doors"]}
        assert doors["left"]["unlocked"] and not doors["right"]["unlocked"]
        assert doors["right"]["name"] == "Elegant Rotunda" and doors["right"]["mana_cost"] == "{2}{W}"

    def test_unlocking_a_door_is_offered_and_taken_as_an_action(self):
        _setup()
        client = TestClient(app)
        sid = client.post("/api/game/replay", json={"numPlayers": 1}).json()["session_id"]
        view = client.post(f"/api/game/{sid}/action", json={
            "type": "edit_add_object", "zone": "battlefield", "owner_id": "p1", "name": ROOM}).json()
        iid = _room(view)["instance_id"]
        for mana_type, value in (("W", 2), ("C", 3)):
            view = client.post(f"/api/game/{sid}/action", json={
                "type": "edit_set_mana", "player_id": "p1", "mana_type": mana_type, "value": value}).json()
        offered = [a for a in view["legal_actions"] if a["type"] == "unlock_door"]
        assert {a["door"] for a in offered} == {"left", "right"}  # a locked Room offers both halves
        view = client.post(f"/api/game/{sid}/action", json={"type": "unlock_door", "instance_id": iid, "door": "right"}).json()
        assert {d["door"] for d in _room(view)["room_doors"] if d["unlocked"]} == {"right"}
        assert {a["door"] for a in view["legal_actions"] if a["type"] == "unlock_door"} == {"left"}


def test_room_token_copy_replay_preserves_both_halves_and_their_unlocked_abilities():
    from mtg_analyzer.game import rooms

    desc = blank_replay(1)
    desc["battlefield"].append({"name": ROOM, "owner_id": "p1", "controller_id": "p1", "unlocked_doors": ["left"]})
    engine = build_replay_engine(desc, _Loader())
    copied = engine.rules.copy_permanent("p1", engine.state.battlefield[0])[0]
    assert copied.is_token and not copied.unlocked_doors
    rooms.unlock(engine.state, copied, rooms.RIGHT)
    restored = build_replay_engine(serialize_replay(engine.state), _Loader())
    token = next(o for o in restored.state.battlefield if o.is_token)
    assert rooms.has_doors(token.card) and token.unlocked_doors == {"right"}
    assert token.mana_value == 3 and token.names == ("Elegant Rotunda",)
    assert token.triggered_abilities and all(a.door == "right" for a in token.triggered_abilities)
    assert rooms.door_cost(token.card, rooms.LEFT).raw == "{1}{W}"
