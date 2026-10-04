"""Local report persistence, validation and retained diagnostic positions."""
import json

from fastapi.testclient import TestClient

from mtg_analyzer import config
from mtg_analyzer.api.app import app
from mtg_analyzer.api.dependencies import get_game_session_manager
from mtg_analyzer.services.game_session import GameSessionManager
from mtg_analyzer.services.replay import blank_replay


def test_report_history_and_rewind(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BUG_REPORT_DIR', tmp_path)
    sessions = GameSessionManager()
    session = sessions.create_replay(blank_replay(), loader=None)
    app.dependency_overrides[get_game_session_manager] = lambda: sessions
    try:
        for life in range(21, 36):
            session.apply_action({'type': 'edit_set_life', 'player_id': 'p1', 'value': life})
        before = session.engine.state.to_dict()
        client = TestClient(app)
        response = client.post('/api/bug-reports', json={
            'description': ' Life is wrong ', 'session_id': session.id,
        })
        assert response.status_code == 201, response.text
        report = json.loads((tmp_path / response.json()['filename']).read_text())
        assert report['description'] == 'Life is wrong'
        assert len(report['game']['recent_actions']) == 12
        assert report['game']['replay']['format'] == 'mtg-replay'
        assert report['game']['recent_actions'][0]['replay_before']['players'][0]['life'] == 23
        assert session.engine.state.to_dict() == before
        assert len(session._history) == 15
        session.rewind(1)
        response = client.post('/api/bug-reports', json={
            'description': 'After undo', 'session_id': session.id, 'action_count': 2,
        })
        report = json.loads((tmp_path / response.json()['filename']).read_text())
        assert len(report['game']['recent_actions']) == 2
        assert report['game']['replay']['players'][0]['life'] == 34
    finally:
        app.dependency_overrides.clear()


def test_report_without_game_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BUG_REPORT_DIR', tmp_path)
    client = TestClient(app)
    response = client.post('/api/bug-reports', json={'description': 'UI bug'})
    assert response.status_code == 201
    report = json.loads((tmp_path / response.json()['filename']).read_text())
    assert report['game'] is None
    for payload in ({'description': ' '}, {'description': 'Bug', 'action_count': 0},
                    {'description': 'Bug', 'action_count': 101}):
        assert client.post('/api/bug-reports', json=payload).status_code == 422
    assert client.post('/api/bug-reports', json={
        'description': 'Bug', 'session_id': 'missing',
    }).status_code == 404
    assert len(list(tmp_path.iterdir())) == 1
