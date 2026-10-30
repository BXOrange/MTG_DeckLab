"""PLR-16: the MCP adapter's pure parts (no `mcp` SDK, no server)."""
import json

import pytest

from mtg_mcp.client import SeatClient, SeatError, action_payload
from mtg_mcp.render import render_state


def _payload(view):
    return {"game": {"name": "T", "status": "running"}, "seat_id": "bot:1", "view": view}


def test_render_before_start():
    text = render_state({"game": {"name": "T", "status": "setup"}, "seat_id": "x", "view": None})
    assert "not started" in text


def test_render_lists_actions_by_index_and_hides_them_from_state():
    text = render_state(_payload({"state": {}, "legal_actions": [{"type": "pass_priority"}, {"type": "x"}]}))
    assert '[0] {"type": "pass_priority"}' in text and "[1]" in text
    assert text.index("## State") < text.index("## Legal actions")
    assert json.dumps("legal_actions") not in text.split("## Legal actions")[0]


def test_render_without_actions_says_so():
    assert "none" in render_state(_payload({"state": {}, "legal_actions": []}))


def test_unreachable_server_is_a_seat_error():
    with pytest.raises(SeatError):
        SeatClient("http://127.0.0.1:9", "t").view()


def test_render_survives_a_response_without_seat_id():
    """POST /action answers with game + view only (api/multiplayer._after_move)."""
    text = render_state({"game": {"name": "T", "status": "running"}, "view": {"legal_actions": []}})
    assert "Legal actions" in text


def test_attack_offer_becomes_one_attacker_declaration_without_mutating_offer():
    offer = {'type': 'attack', 'instance_id': 7,
             'legal_defenders': [{'kind': 'player', 'id': 'opponent', 'label': 'Opponent'}]}
    payload = action_payload(offer)
    assert payload['type'] == 'declare_attackers'
    assert payload['instance_ids'] == [7]
    assert payload['defender'] == {'kind': 'player', 'id': 'opponent'}
    assert offer['type'] == 'attack'


def test_attack_with_multiple_defenders_requires_an_explicit_choice():
    offer = {'type': 'attack', 'instance_id': 7,
             'legal_defenders': [{'kind': 'player', 'id': 'p'}, {'kind': 'planeswalker', 'instance_id': 8}]}
    with pytest.raises(SeatError, match='defender'):
        action_payload(offer)
    assert action_payload(offer, {'defender': {'kind': 'planeswalker', 'instance_id': 8}})['defender']['instance_id'] == 8


def test_adapter_without_token_fails_clearly_before_starting_sdk(monkeypatch, capsys):
    from mtg_mcp.server import main
    monkeypatch.delenv('MTG_MCP_SERVER_TOKEN', raising=False)
    with pytest.raises(SystemExit) as result:
        main([])
    assert result.value.code == 2
    assert 'server token missing' in capsys.readouterr().err


def test_server_token_is_persistent_private_and_rotatable(tmp_path, monkeypatch):
    import os
    import stat
    from mtg_analyzer.services import mcp_credentials

    path = tmp_path / 'token'
    monkeypatch.setattr(mcp_credentials, '_path', lambda: path)
    assert not mcp_credentials.matches('')
    first = mcp_credentials.rotate_token()
    assert mcp_credentials.matches(first)
    assert mcp_credentials.read_token() == first
    if os.name == 'posix':
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    second = mcp_credentials.rotate_token()
    assert first != second
    assert not mcp_credentials.matches(first)
    assert mcp_credentials.matches(second)
