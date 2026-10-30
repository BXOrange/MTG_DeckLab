"""PLR-16: optional SDK client -> stdio adapter -> live token API -> a whole game."""
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip('mcp', reason='optional MCP SDK; install requirements-mcp.txt')
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from tests.api.test_api_multiplayer import env, TestMcpSeat as _McpSeatTests

# Bound server startup and the pass/choice loop so transport failures cannot hang CI.
SERVER_STARTUP_SECONDS = 5
SERVER_POLL_SECONDS = .01
MAX_MATCH_ACTIONS = 400
# An actual MCP subprocess and HTTP server need a startup budget above unit tests.
@pytest.mark.timeout(45)
def test_stdio_client_plays_from_setup_to_combat_victory(env, tmp_path):
    import uvicorn

    gid, host, seat_id, token, _ = _McpSeatTests()._table(env)
    http = env['client']
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    base_url = f'http://127.0.0.1:{listener.getsockname()[1]}'
    server = uvicorn.Server(uvicorn.Config(http.app, log_level='error', access_log=False, lifespan='off'))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    deadline = time.monotonic() + SERVER_STARTUP_SECONDS
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(SERVER_POLL_SECONDS)
    assert server.started

    async def play():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'mtg_mcp'], cwd=str(tmp_path),
                                       env={'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
                                            'MTG_BASE_URL': base_url, 'MTG_MCP_SERVER_TOKEN': env['mcp_server_token']})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                assert {tool.name for tool in (await mcp.list_tools()).tools} == {
                    'select_seat', 'get_state', 'wait_for_turn', 'submit_action', 'yield_priority', 'set_name', 'get_decklist', 'concede'}

                async def call(name, arguments=None):
                    result = await mcp.call_tool(name, arguments or {})
                    assert not getattr(result, 'is_error', getattr(result, 'isError', False))
                    text = '\n'.join(block.text for block in result.content if hasattr(block, 'text'))
                    assert not text.startswith(('Error:', 'Rejected:')), text
                    return text

                assert 'not started' in await call('select_seat', {'seat_token': token})
                assert 'not started' in await call('get_state')
                assert 'yield mode unavailable' in await call('yield_priority', {'mode': 'end_step'})
                assert 'stdio player' in await call('set_name', {'name': 'stdio player'})
                assert '99 Forest' in await call('get_decklist')
                http.post(f'/api/multiplayer/games/{gid}/ready', json={'playerId': host})
                started = http.post(f'/api/multiplayer/games/{gid}/start', json={'playerId': host})
                assert started.status_code == 200, started.text
                session = env['sessions'].get(started.json()['view']['session_id'])
                # Short deterministic fixture: the real 100-card decks and 1/1
                # commander play normally; two combat hits finish the game.
                session.engine.state.player_by_id(host).life = 2
                did_attack = False
                did_explicit_yield = False
                for _ in range(MAX_MATCH_ACTIONS):
                    payload = await call('wait_for_turn', {'timeout_seconds': 0})
                    encoded = payload.split('## State\n', 1)[1].split('\n## Legal actions', 1)[0]
                    view = json.loads(encoded)
                    state = view['state']
                    if state['game_over']:
                        assert state['winner_id'] == seat_id
                        assert did_attack
                        assert did_explicit_yield
                        assert "set_yield" in session.move_log
                        return
                    opponent = next(player for player in state['players'] if player['id'] == host)
                    assert opponent['hand'] == []
                    actions = []
                    for line in payload.splitlines():
                        if line.startswith('[') and '] ' in line:
                            index, encoded_action = line[1:].split('] ', 1)
                            actions.append((int(index), json.loads(encoded_action)))
                    if actions:
                        if (not did_explicit_yield and state['active_player_id'] == seat_id
                                and state['current_step'] == 'main1' and not state.get('stack')
                                and not view.get('pending_choice')):
                            result = await call('yield_priority', {'mode': 'end_step'})
                            assert result.startswith('Yield applied.'), result
                            did_explicit_yield = True
                            continue
                        preference = {'keep_hand': 0, 'play_land': 1, 'cast_spell': 2, 'attack': 3, 'pass_priority': 9}
                        index, action = min(actions, key=lambda pair: preference.get(pair[1]['type'], 8))
                        args = {'index': index, 'expected_type': action['type']}
                        if action['type'] == 'attack':
                            did_attack = True
                        result = await call('submit_action', args)
                        assert result.startswith('Action applied.'), result
                    else:
                        own_view = session.view(perspective=host)
                        offers = own_view['legal_actions']
                        chosen = next((action for action in offers if action['type'] == 'keep_hand'), None)
                        chosen = chosen or next((action for action in offers if action['type'] == 'pass_priority'), None)
                        if chosen is None and any(action['type'] == 'declare_blockers' for action in offers):
                            chosen = {'type': 'declare_blockers', 'assignments': []}
                        chosen = chosen or next((action for action in offers if action['type'] == 'choose'), None)
                        assert chosen is not None, {'step': own_view['state']['current_step'], 'actions': offers, 'pending': own_view['state']['pending_choice']}
                        response = http.post(f'/api/multiplayer/games/{gid}/action',
                                             json={'playerId': host, 'action': chosen})
                        assert response.status_code == 200, response.text
                pytest.fail('The MCP client did not finish its match within the bounded action count')

    try:
        asyncio.run(play())
    finally:
        server.should_exit = True
        thread.join(timeout=SERVER_STARTUP_SECONDS)
        listener.close()
