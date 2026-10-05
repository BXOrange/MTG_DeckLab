"""Tests for the solo-vs-bots HTTP API (PLR-14, `mtg_analyzer/api/solo.py`).

The Multiplayer engine without the lobby: one human seat (`SOLO_HUMAN_ID`),
1-3 `services/bots.py` bots, plain REST. These exercise the whole loop —
start → mulligan → play, with one bot action per view poll and every human
priority window preserved — plus the RULE 400.2 redaction that a
solo-but-still-multiplayer session applies to the bot seats' hands.
"""

import pytest
from fastapi.testclient import TestClient

from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import (
    get_deck_database,
    get_game_session_manager,
    get_lazy_card_loader,
)
from mtg_analyzer.api.solo import SOLO_DEFAULT_PLAYER_NAME, SOLO_HUMAN_ID
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.decks.deck import Deck
from mtg_analyzer.services.deck_database import DeckDatabase
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.lazy_card_loader import LoadCardsResult


def _forest():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def _commander():
    return Card(
        id="Cmdr", name="Test Commander", type_line="Legendary Creature — Elf",
        is_creature=True, power=1, toughness=1, color_identity=set(),
    )


class _FakeLoader:
    def __init__(self, cards):
        self._cards = cards

    def load_cards(self, names):
        found = {n: self._cards[n] for n in names if n in self._cards}
        return LoadCardsResult(cards=found, not_found=[n for n in names if n not in self._cards])


@pytest.fixture
def env():
    sessions = GameSessionManager()
    decks = DeckDatabase()
    loader = _FakeLoader({"Forest": _forest(), "Test Commander": _commander()})
    app.dependency_overrides[get_game_session_manager] = lambda: sessions
    app.dependency_overrides[get_deck_database] = lambda: decks
    app.dependency_overrides[get_lazy_card_loader] = lambda: loader
    yield {"client": TestClient(app), "sessions": sessions, "decks": decks}
    for dep in (get_game_session_manager, get_deck_database, get_lazy_card_loader):
        app.dependency_overrides.pop(dep, None)


def _legal_deck(decks, name="Mono-G", color_identity=None):
    """A playable saved deck. ``color_identity`` is what a deck the client
    has already listed once carries (`api/saved_decks._ensure_identity`) —
    left `None` here by default, i.e. not computed yet, mirroring
    `test_api_multiplayer.py`'s own `_legal_deck`."""
    deck = Deck(
        name=name,
        commander_text="1 Test Commander\n",
        mainboard_text="99 Forest\n",
        color_identity=color_identity,
    )
    decks.save_deck(deck)
    return deck


def _player(view, player_id):
    return next(p for p in view["state"]["players"] if p["id"] == player_id)


_SENTINEL = object()


def _start(client, deck_id, opponents=_SENTINEL, **kw):
    if opponents is _SENTINEL:
        opponents = [{"kind": "goldfish", "deckId": deck_id}]
    return client.post(
        "/api/solo/start", json={"deckId": deck_id, "opponents": opponents, **kw}
    )


def _bot_ids(view):
    return [p["id"] for p in view["state"]["players"] if p["id"] != SOLO_HUMAN_ID]


def _controls(view, player_id, *, is_land=None):
    out = [o for o in view["state"]["battlefield"] if o.get("controller_id") == player_id]
    if is_land is not None:
        out = [o for o in out if bool(o.get("is_land")) == is_land]
    return out


# -- start ----------------------------------------------------------------


def test_start_returns_the_human_view_in_setup_with_the_bot_seated(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    res = _start(client, deck.id)
    assert res.status_code == 200, res.json()
    view = res.json()
    assert view["perspective"] == SOLO_HUMAN_ID
    assert view["mode"] == "multiplayer"  # the engine underneath
    assert view["setup"] and not view["setup"]["complete"]
    ids = [p["id"] for p in view["state"]["players"]]
    assert SOLO_HUMAN_ID in ids and len(ids) == 2


def test_human_seat_is_named_after_the_profil_player_name(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id, playerName="  Alice ").json()
    assert _player(view, SOLO_HUMAN_ID)["name"] == "Alice"
    # No (or blank) name falls back to the default label.
    for kw in ({}, {"playerName": "   "}):
        view = _start(client, deck.id, **kw).json()
        assert _player(view, SOLO_HUMAN_ID)["name"] == SOLO_DEFAULT_PLAYER_NAME


def test_start_carries_the_configurable_pass_timer_into_the_view(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    # Default: the server value.
    view = _start(client, deck.id).json()
    assert view["priority"]["timer_seconds"] == 20
    # Explicit override, clamped like the multiplayer one.
    view = _start(client, deck.id, spellTimerSeconds=5).json()
    assert view["priority"]["timer_seconds"] == 5
    view = _start(client, deck.id, spellTimerSeconds=0).json()
    assert view["priority"]["timer_seconds"] == 0


def test_deck_colour_identity_becomes_the_seat_banner(env):
    # Same "fly the deck's own colours" default Multiplayer gives a seat
    # (`test_api_multiplayer.py`'s `test_deck_colour_identity_is_the_default_
    # banner`) — there's no lobby here, so `api/solo.py` computes it at
    # start and hands it to `GameSession._banner_colors` directly.
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks, color_identity=["G", "U"])
    view = _start(client, deck.id).json()
    assert _player(view, SOLO_HUMAN_ID)["banner_color"] == "ug"


def test_an_uncomputed_identity_leaves_the_seat_unpainted(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)  # colour identity not computed yet (None)
    view = _start(client, deck.id).json()
    assert "banner_color" not in _player(view, SOLO_HUMAN_ID)


def test_each_bot_flies_its_own_decks_identity(env):
    # The human and each bot are independent seats — one seat's colours
    # must never bleed onto another's banner.
    client, decks = env["client"], env["decks"]
    human_deck = _legal_deck(decks, name="Human", color_identity=["R"])
    bot_deck = _legal_deck(decks, name="Bot", color_identity=["W", "B"])
    view = _start(
        client, human_deck.id, opponents=[{"kind": "goldfish", "deckId": bot_deck.id}]
    ).json()
    assert _player(view, SOLO_HUMAN_ID)["banner_color"] == "r"
    assert _player(view, _bot_ids(view)[0])["banner_color"] == "wb"


def test_start_rejects_an_unknown_deck(env):
    res = _start(env["client"], "does-not-exist")
    assert res.status_code == 422


def test_start_rejects_zero_and_too_many_opponents(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    assert _start(client, deck.id, opponents=[]).status_code == 400
    four = [{"kind": "goldfish", "deckId": deck.id} for _ in range(4)]
    assert _start(client, deck.id, opponents=four).status_code == 400


def test_start_rejects_an_unknown_bot_kind(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    res = _start(client, deck.id, opponents=[{"kind": "wizard", "deckId": deck.id}])
    assert res.status_code == 400


def test_the_bots_hand_is_redacted_from_the_human_view(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    bot_id = _bot_ids(view)[0]
    bot = next(p for p in view["state"]["players"] if p["id"] == bot_id)
    me = next(p for p in view["state"]["players"] if p["id"] == SOLO_HUMAN_ID)
    # RULE 400.2 — the human sees their own opening hand, not the bot's.
    assert len(me["hand"]) == 7
    assert not any(c.get("name") for c in bot["hand"]), bot["hand"]


# -- playing ------------------------------------------------------------------


def _session_id(view):
    return view["session_id"]


def _next_view(client, view):
    """One human pass or one bot tick, as the board does."""
    sid = _session_id(view)
    choice = next((a for a in view['legal_actions'] if a['type'] == 'choose'), None)
    if choice:
        response = client.post(f'/api/solo/{sid}/action', json=choice)
    elif any(a['type'] == 'pass_priority' for a in view['legal_actions']):
        response = client.post(f'/api/solo/{sid}/action', json={'type': 'pass_priority'})
    else:
        response = client.get(f'/api/solo/{sid}')
    assert response.status_code == 200, response.text
    return response.json()


def test_keep_hand_completes_setup_and_hands_the_human_priority(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    res = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    assert res.status_code == 200, res.json()
    view = res.json()
    assert view["setup"]["complete"]
    # The human is seat 0 (on the play) — it's their turn, and they have
    # actions to take (at minimum, passing priority).
    assert view["state"]["active_player_id"] == SOLO_HUMAN_ID
    assert view["legal_actions"]


def test_passing_through_the_turn_lets_the_bot_play_a_land(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    view = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}).json()
    bot_id = _bot_ids(view)[0]

    for _ in range(80):
        view = _next_view(client, view)
        if view.get("state", {}).get("game_over"):
            break
        if _controls(view, bot_id, is_land=True):
            break
    # The GoldfishBot plays a land every one of its turns — by the time the
    # game has come back around to the human a few times, one is on the board.
    assert _controls(view, bot_id, is_land=True), (
        f"turn {view['state']['internal_turn']['number']}, bot board {_controls(view, bot_id)}"
    )


@pytest.mark.parametrize('bot_count', [1, 3])
def test_each_request_returns_after_one_action(env, bot_count):
    """Human actions and bot ticks each expose their own resulting position."""
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id, opponents=[{'kind': 'goldfish', 'deckId': deck.id}] * bot_count).json()
    sid = _session_id(view)
    view = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}).json()
    start_turn = view["state"]["internal_turn"]["number"]
    for _ in range(80):
        previous_count = len(view['move_log'])
        view = _next_view(client, view)
        assert len(view['move_log']) == previous_count + 1
        if not view['legal_actions'] and not view['state']['game_over']:
            assert view['bot_action_pending']
    assert view["state"]["internal_turn"]["number"] > start_turn  # the game moved on


def test_bot_turn_preserves_human_pass_only_windows(env):
    """Solo has the same human priority windows as a shared table."""
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    view = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}).json()

    saw_own_turn_again = False
    saw_pass_only_window = False
    for _ in range(80):
        view = _next_view(client, view)
        state = view["state"]
        if state["game_over"]:
            break
        if state["active_player_id"] != SOLO_HUMAN_ID:
            if {a['type'] for a in view['legal_actions']} == {'pass_priority'}:
                saw_pass_only_window = True
                polled = client.get(f'/api/solo/{sid}').json()
                assert polled['move_log'] == view['move_log']
                assert polled['state']['priority_player_id'] == SOLO_HUMAN_ID
        elif state["internal_turn"]["number"] > 1:
            saw_own_turn_again = True
    assert saw_own_turn_again  # the loop really did cross a bot turn
    assert saw_pass_only_window


def _to_bots_turn(client, sid, view):
    """Pass the human's turn away until a bot's turn begins."""
    for _ in range(120):
        if view["state"]["active_player_id"] != SOLO_HUMAN_ID:
            return view
        if view["state"]["priority_player_id"] == SOLO_HUMAN_ID:
            view = client.post(f"/api/solo/{sid}/action", json={"type": "pass_priority"}).json()
        else:
            view = client.get(f"/api/solo/{sid}").json()
    raise AssertionError("never reached the bot's turn")


def test_passing_this_turn_yields_the_humans_windows_but_not_the_bots_actions(env):
    """VIS-12: an armed yield is the one case the server passes for the
    human — and every bot action is still exposed one request at a time."""
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    view = client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []}).json()
    view = _to_bots_turn(client, sid, view)
    bots_turn = view["state"]["internal_turn"]["number"]
    view = client.post(f"/api/solo/{sid}/action", json={"type": "set_yield", "mode": "turn"}).json()
    assert view["priority"]["yields"] == {SOLO_HUMAN_ID: "turn"}

    for _ in range(80):
        if view["state"]["internal_turn"]["number"] > bots_turn:
            break
        # The bot's turn is its own, and the human is passed for throughout.
        assert view["state"]["priority_player_id"] != SOLO_HUMAN_ID
        before = len(view["move_log"])
        view = client.get(f"/api/solo/{sid}").json()
        assert len(view["move_log"]) <= before + 1
    assert view["state"]["internal_turn"]["number"] > bots_turn
    assert view["priority"]["yields"] == {}


def test_passing_this_turn_is_refused_on_the_humans_own_turn(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    res = client.post(f"/api/solo/{sid}/action", json={"type": "set_yield", "mode": "turn"})
    assert res.status_code == 400


# -- concede / restart / lifecycle ------------------------------------------


def test_concede_ends_the_game_in_the_bots_favour(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    view = client.post(f"/api/solo/{sid}/concede").json()
    assert view["state"]["game_over"]
    assert view["state"]["winner_id"] in _bot_ids(view)


def test_restart_returns_to_setup_with_the_bot_kept_again(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    view = _start(client, deck.id).json()
    sid = _session_id(view)
    client.post(f"/api/solo/{sid}/action", json={"type": "keep_hand", "bottom_instance_ids": []})
    view = client.post(f"/api/solo/{sid}/restart").json()
    assert view["setup"] and not view["setup"]["complete"]
    assert view["state"]["active_player_id"] == SOLO_HUMAN_ID


def test_get_view_and_delete(env):
    client, decks = env["client"], env["decks"]
    deck = _legal_deck(decks)
    sid = _session_id(_start(client, deck.id).json())
    assert client.get(f"/api/solo/{sid}").json()["perspective"] == SOLO_HUMAN_ID
    assert client.delete(f"/api/solo/{sid}").json() == {"deleted": True}
    assert client.get(f"/api/solo/{sid}").status_code == 404
    assert client.delete(f"/api/solo/{sid}").status_code == 404


def test_smart_bot_is_selectable_and_retains_own_strategy_on_restart(env):
    deck = _legal_deck(env['decks'])
    response = _start(env['client'], deck.id, opponents=[{'kind': 'smart', 'deckId': deck.id}])
    assert response.status_code == 200, response.json()
    v = response.json()
    session = env['sessions'].get(v['session_id'])
    bot_id = _bot_ids(v)[0]
    strategy = session._bot_strategies[bot_id]
    assert strategy.commanders == {'test commander'}
    assert _player(v, bot_id)['hand'] == []
    restarted = env['client'].post(f"/api/solo/{v['session_id']}/restart")
    assert restarted.status_code == 200
    assert session._bot_strategies[bot_id] is strategy


def test_ai_bot_completed_job_advances_on_solo_view_poll(env):
    from tests.services.test_ai_bot import Client, Settings
    client = env['client']
    deck = _legal_deck(env['decks'])
    response = _start(client, deck.id, opponents=[{'kind':'ai', 'deckId':deck.id}])
    assert response.status_code == 200
    session_id = response.json()['session_id']
    session = env['sessions'].get(session_id)
    policy = next(iter(session._solo_bots.values()))
    policy.client = Client()
    policy.settings_store = Settings()
    response = client.post(f'/api/solo/{session_id}/action', json={'type':'keep_hand', 'bottom_instance_ids':[]})
    assert response.status_code == 200, response.text
    # Pass the human through turn one until the AI has a pending decision.
    for _ in range(80):
        if policy.context.get('future'):
            break
        actions = session.legal_actions(perspective=SOLO_HUMAN_ID)
        if any(a['type'] == 'pass_priority' for a in actions):
            response = client.post(f'/api/solo/{session_id}/action', json={'type':'pass_priority'})
            assert response.status_code == 200, response.text
        else:
            response = client.get(f'/api/solo/{session_id}')
    assert policy.context.get('future') is not None
    policy.context['future'].result(timeout=5)
    result = client.get(f'/api/solo/{session_id}')
    assert result.status_code == 200
    assert _controls(result.json(), policy.player_id, is_land=True)
    sent = policy.client.payloads[0]['state']['players']
    assert next(p for p in sent if p['id'] == SOLO_HUMAN_ID)['hand'] == []
    assert all(p['library'] == [] for p in sent)
