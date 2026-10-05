"""Table-chat transport: seat validation, broadcast and no bot advancement."""
from tests.api.test_api_multiplayer import env, _seated_game, _connect
from mtg_analyzer.api import multiplayer


def test_emote_broadcasts_without_running_bots_and_uses_the_request_seat(env, monkeypatch):
    client = env['client']
    gid, ann, bob = _seated_game(env)
    started = client.post(f'/api/multiplayer/games/{gid}/start', json={'playerId': ann})
    assert started.status_code == 200, started.text
    session = env['sessions'].get(started.json()['view']['session_id'])
    before = session.engine.state.to_dict()
    broadcasts = []
    async def broadcast(game, shared):
        broadcasts.append((game.id, shared))
    def forbidden(*args, **kwargs):
        raise AssertionError('chat must not drive bots')
    monkeypatch.setattr(multiplayer.lobby_connections, 'broadcast_game', broadcast)
    monkeypatch.setattr(multiplayer, 'run_bots', forbidden)
    response = client.post(f'/api/multiplayer/games/{gid}/action', json={
        'playerId': bob, 'action': {'type': 'emote', 'emote': '👍', 'actor_id': ann},
    })
    assert response.status_code == 200, response.text
    assert session.engine.state.to_dict() == before
    assert broadcasts == [(gid, session)]
    message = response.json()['view']['table_messages'][-1]
    assert message['author'] == 'Bob' and message['actor_id'] == bob
    assert session.view(perspective=ann)['table_messages'][-1] == message
    assert session.view(perspective=bob)['table_messages'][-1] == message
    observer = _connect(client, 'Watcher')
    denied = client.post(f'/api/multiplayer/games/{gid}/action', json={
        'playerId': observer, 'action': {'type': 'emote', 'emote': '👍'},
    })
    assert denied.status_code == 403
    assert len(session.table_feed.view()) == 1
