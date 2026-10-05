"""VIS-4: public announcements and conversation must not change gameplay."""
import pytest
from tests.services.test_bots import make_game, keep, bear
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameActionError
from mtg_analyzer.services.table_feed import MAX_TABLE_MESSAGES


def main_phase(session):
    keep(session, 'ann', 'bob')
    while session.engine.state.current_step != 'main1':
        session.apply_action({'type': 'pass_priority'}, actor_id=session.engine.state.priority_player.id)


def test_chat_is_shared_without_consuming_priority_history_or_pending_choices():
    session = make_game()
    main_phase(session)
    session.set_ui_draft('bob', {'kind': 'block'})
    session.engine.state.pending_choice = {'kind': 'test', 'player_id': 'ann', 'options': []}
    before = session.engine.state.to_dict()
    history = len(session._history)
    moves = list(session.move_log)
    session.apply_action({'type': 'emote', 'emote': '👍', 'author': 'spoofed'}, actor_id='bob')
    assert session.engine.state.to_dict() == before
    assert len(session._history) == history
    assert session.move_log == moves
    assert session.view(perspective='bob')['ui_draft'] == {'kind': 'block'}
    message = session.view(perspective='ann')['table_messages'][-1]
    assert message['author'] == 'Bob'
    assert message['text'] == '👍'
    assert session.observer_view()['table_messages'][-1] == message


@pytest.mark.parametrize('text', ['', '  ', None, 'arbitrary text', ['👍']])
def test_invalid_chat_does_not_change_feed(text):
    session = make_game()
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'emote', 'emote': text}, actor_id='bob')
    assert session.table_feed.view() == []


def test_announcements_use_real_card_names_and_exclude_passes_and_failed_moves():
    session = make_game()
    main_phase(session)
    action = next(a for a in session.legal_actions('ann') if a['type'] == 'play_land')
    session.apply_action({**action, 'name': 'secret or spoofed name'}, actor_id='ann')
    message = session.table_feed.view()[-1]
    assert message['action'] == 'play_land'
    assert message['author'] == 'Ann'
    assert message['card_name'] == 'Forest'
    with pytest.raises(GameActionError):
        session.apply_action(action, actor_id='ann')
    session.apply_action({'type': 'pass_priority'}, actor_id='ann')
    assert session.table_feed.view() == [message]


def test_mana_and_spell_announcements_remain_visible_after_the_card_moves():
    session = make_game()
    main_phase(session)
    land = next(a for a in session.legal_actions('ann') if a['type'] == 'play_land')
    session.apply_action(land, actor_id='ann')
    mana = next(a for a in session.legal_actions('ann') if a['type'] == 'tap_for_mana')
    session.apply_action(mana, actor_id='ann')
    spell = GameObject(bear('Test Bear', '{G}', 1), owner_id='ann')
    session.engine.state.player_by_id('ann').add_to_zone(spell, Zone.HAND)
    cast = next(a for a in session.legal_actions('ann') if a['type'] == 'cast_spell')
    session.apply_action(cast, actor_id='ann')
    messages = session.table_feed.view()
    assert [m['action'] for m in messages] == ['play_land', 'tap_for_mana', 'cast_spell']
    assert messages[-1]['card_name'] == 'Test Bear'
    assert messages[-1] == session.view(perspective='bob')['table_messages'][-1]


def test_undo_removes_announcements_but_preserves_chat_and_restart_clears_feed():
    session = make_game()
    main_phase(session)
    action = next(a for a in session.legal_actions('ann') if a['type'] == 'play_land')
    session.apply_action(action, actor_id='ann')
    session.apply_action({'type': 'emote', 'emote': '🤔'}, actor_id='ann')
    session.rewind()
    assert [m['kind'] for m in session.table_feed.view()] == ['emote']
    session.apply_action(action, actor_id='ann')
    assert len(session.table_feed.view()) == 2
    session.restart()
    assert session.table_feed.view() == []


def test_transcript_is_bounded_and_survives_a_view_reconnect():
    session = make_game()
    for i in range(MAX_TABLE_MESSAGES + 2):
        session.table_feed.emote(session.engine.state.player_by_id('ann'), '👍', 1)
    messages = session.view(perspective='bob')['table_messages']
    assert len(messages) == MAX_TABLE_MESSAGES
    assert messages[0]['id'] == 3
    assert messages == session.view(perspective='bob')['table_messages']


def test_activation_announces_the_actual_source_and_ability_text():
    from mtg_analyzer.game.effects.core import ActivatedAbility, DrawCardEffect
    from mtg_analyzer.game.costs import parse_activation_cost
    session = make_game()
    main_phase(session)
    land = next(a for a in session.legal_actions('ann') if a['type'] == 'play_land')
    session.apply_action(land, actor_id='ann')
    source = session.engine.state.find_object(land['instance_id'])
    source.activated_abilities.append(ActivatedAbility(
        effects=[DrawCardEffect(1)], cost=parse_activation_cost('{0}'),
        source=source, description='Draw a card.',
    ))
    activation = next(a for a in session.legal_actions('ann') if a['type'] == 'activate_ability')
    session.apply_action(activation, actor_id='ann')
    message = session.table_feed.view()[-1]
    assert message['action'] == 'activate_ability'
    assert message['card_name'] == 'Forest'
    assert message['ability_text'] == 'Draw a card.'


def test_auto_payment_also_announces_mana_abilities():
    session = make_game()
    main_phase(session)
    land = next(a for a in session.legal_actions('ann') if a['type'] == 'play_land')
    session.apply_action(land, actor_id='ann')
    spell = GameObject(bear('Test Bear', '{G}', 1), owner_id='ann')
    session.engine.state.player_by_id('ann').add_to_zone(spell, Zone.HAND)
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id}, actor_id='ann')
    assert [m['action'] for m in session.table_feed.view()] == ['play_land', 'tap_for_mana', 'cast_spell']


def test_face_down_spell_does_not_reveal_its_identity_to_chat():
    from tests.test_face_down_permanents import morph_card
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    session = make_game()
    main_phase(session)
    spell = GameObject(morph_card(), owner_id='ann', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player = session.engine.state.player_by_id('ann')
    player.add_to_zone(spell, Zone.HAND)
    player.mana_pool.add('C', 3)
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id, 'face': 'face_down'}, actor_id='ann')
    messages = session.view(perspective='bob')['table_messages']
    assert len(messages) == 1
    assert 'Willbender' not in str(messages)
    assert messages[0]['action'] == 'cast_spell'


def test_free_text_chat_is_not_an_available_action():
    session = make_game()
    main_phase(session)
    with pytest.raises(GameActionError):
        session.apply_action({'type': 'chat', 'text': 'hello'}, actor_id='ann')
    assert session.table_feed.view() == []


def test_hand_mana_activation_announces_the_exiled_source():
    from tests.test_auto_tap_action import _spirit_guide
    session = make_game()
    main_phase(session)
    player = session.engine.state.player_by_id('ann')
    guide = GameObject(_spirit_guide(), owner_id='ann', zone=Zone.HAND)
    player.add_to_zone(guide, Zone.HAND)
    spell = GameObject(bear('Test Bear', '{G}', 1), owner_id='ann')
    player.add_to_zone(spell, Zone.HAND)
    session.apply_action({'type': 'activate_hand_mana', 'instance_id': guide.instance_id}, actor_id='ann')
    session.apply_action({'type': 'cast_spell', 'instance_id': spell.instance_id}, actor_id='ann')
    messages = session.table_feed.view()
    assert [m['action'] for m in messages] == ['activate_hand_mana', 'cast_spell']
    assert messages[0]['card_name'] == guide.card.name


def test_free_cast_during_resolution_is_announced_even_when_request_is_a_pass():
    from mtg_analyzer.game.effects.core import GameEffect
    from mtg_analyzer.models.game.game_state import StackItem
    session = make_game()
    main_phase(session)
    player = session.engine.state.player_by_id('ann')
    spell = GameObject(bear('Free Bear', '{0}', 0), owner_id='ann', zone=Zone.HAND)
    player.add_to_zone(spell, Zone.HAND)
    class FreeCast(GameEffect):
        def apply(self, context, targets=None):
            context.engine.cast_without_paying(player, spell)
    session.engine.state.stack.append(StackItem(kind='ability', controller_id='ann', effects=[FreeCast()]))
    session.apply_action({'type': 'pass_priority'}, actor_id='ann')
    session.apply_action({'type': 'pass_priority'}, actor_id='bob')
    messages = session.table_feed.view()
    assert len(messages) == 1
    assert messages[0]['action'] == 'cast_spell'
    assert messages[0]['card_name'] == 'Free Bear'
