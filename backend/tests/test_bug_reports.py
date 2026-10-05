"""Local report persistence, validation and retained diagnostic positions."""
import json
import gzip

from mtg_analyzer.services.bug_report_codec import encode_report, decode_report, load_report

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
        path = tmp_path / response.json()['filename']
        assert path.name.endswith('.json.gz')
        with gzip.open(path, 'rt', encoding='utf-8') as handle:
            stored = json.load(handle)
        assert stored['version'] == 2
        assert 'state' not in stored['game']
        report = load_report(path)
        assert report['game'] == session.bug_report_context(12)
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
        report = load_report(tmp_path / response.json()['filename'])
        assert len(report['game']['recent_actions']) == 2
        assert report['game']['replay']['players'][0]['life'] == 34
    finally:
        app.dependency_overrides.clear()


def test_report_without_game_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BUG_REPORT_DIR', tmp_path)
    client = TestClient(app)
    response = client.post('/api/bug-reports', json={'description': 'UI bug'})
    assert response.status_code == 201
    report = load_report(tmp_path / response.json()['filename'])
    assert report['game'] is None
    for payload in ({'description': ' '}, {'description': 'Bug', 'action_count': 0},
                    {'description': 'Bug', 'action_count': 101}):
        assert client.post('/api/bug-reports', json=payload).status_code == 422
    assert client.post('/api/bug-reports', json={
        'description': 'Bug', 'session_id': 'missing',
    }).status_code == 404
    assert len(list(tmp_path.iterdir())) == 1


def test_codec_lossless_card_variants_and_deltas(tmp_path):
    card = {'card_id': 'same', 'name': 'Front', 'type_line': 'Creature',
            'instance_id': 'a', 'power': 2, 'tapped': False}
    variant = {**card, 'name': 'Back', 'power': 4}
    token = {**card, 'card_id': None, 'token': {'name': 'Soldier', 'power': 1}}
    report = {'version': 1, 'game': {
        'replay': {'objects': [variant, token]},
        'state': {'objects': [variant], 'choice': None},
        'recent_actions': [
            {'label': 'change', 'replay_before': {'objects': [card, card]},
             'state_before': {'objects': [card], 'removed': True}},
            {'label': 'transform', 'replay_before': {'objects': [card]},
             'state_before': {'objects': [card], 'choice': {'options': [1, 2]}}},
        ],
    }}
    original = json.loads(json.dumps(report))
    encoded = encode_report(report)
    assert report == original
    assert len(encoded['game']['cards']) == 3
    assert decode_report(json.loads(json.dumps(encoded))) == original
    assert decode_report(original) == original
    legacy = tmp_path / 'old.json'
    legacy.write_text(json.dumps(original))
    assert load_report(legacy) == original
    compressed = tmp_path / 'new.json.gz'
    with gzip.open(compressed, 'wt') as handle:
        json.dump(encoded, handle)
    assert load_report(compressed) == original
    report['game']['recent_actions'] = []
    assert decode_report(encode_report(report)) == report
