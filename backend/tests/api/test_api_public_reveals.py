"""VIS-17: real priority resolution publishes only the revealed card to every seat."""
from tests.api.test_api_multiplayer import env, _seated_game, _connect
from mtg_analyzer.game.effects.core import ActivatedAbility
from mtg_analyzer.game.effects.damage_draw import RevealTopEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def test_resolved_reveal_is_public_over_multiplayer_api(env):
    client = env['client']
    gid, ann, bob = _seated_game(env)
    response = client.post(f'/api/multiplayer/games/{gid}/start', json={'playerId': ann})
    assert response.status_code == 200, response.text
    session = env['sessions'].get(response.json()['view']['session_id'])
    for pid in (ann, bob):
        session.apply_action({'type': 'keep_hand'}, actor_id=pid)
    state = session.engine.state
    while state.current_step != 'main1':
        session.apply_action({'type': 'pass_priority'}, actor_id=state.priority_player.id)
    active = state.active_player
    source = GameObject(Card(id='reveal-source', name='Reveal source', type_line='Artifact'),
                        owner_id=active.id, zone=Zone.BATTLEFIELD)
    source.controller_id = active.id
    state.add_to_battlefield(source)
    source.activated_abilities = [ActivatedAbility([RevealTopEffect(source=source)], source=source)]
    top = active.library[-1]
    response = client.post(f'/api/multiplayer/games/{gid}/action', json={
        'playerId': active.id,
        'action': {'type': 'activate_ability', 'instance_id': source.instance_id, 'ability_index': 0},
    })
    assert response.status_code == 200, response.text
    for _ in range(4):
        if not state.stack:
            break
        response = client.post(f'/api/multiplayer/games/{gid}/action', json={
            'playerId': state.priority_player.id, 'action': {'type': 'pass_priority'},
        })
        assert response.status_code == 200, response.text
    assert not state.stack
    watcher = _connect(client, 'Watcher')
    assert client.post(f'/api/multiplayer/games/{gid}/observe', json={'playerId': watcher}).status_code == 200
    for pid in (ann, bob, watcher):
        response = client.get(f'/api/multiplayer/games/{gid}', params={'player_id': pid})
        assert response.status_code == 200, response.text
        view = response.json()['view']
        revealed = next(message for message in view['table_messages'] if message['action'] == 'reveal')
        assert revealed['revealed_card']['instance_id'] == top.instance_id
        assert revealed['card_id'] == top.card.id
        owner = next(player for player in view['state']['players'] if player['id'] == active.id)
        assert [card['instance_id'] for card in owner['library']] == [top.instance_id]
        if pid != active.id:
            assert owner['hand'] == []
        assert view['state']['known_cards'][0]['library_position'] == 1
