"""VIS-17: public knowledge never discloses unobserved hidden cards."""
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.game.events import EventType, GameEvent
from tests.services.test_bots import make_game, keep, bear


def game():
    session = make_game(ann_deck=[bear(f'Known {i}') for i in range(20)],
                        bob_deck=[bear(f'Other {i}') for i in range(20)])
    keep(session, 'ann', 'bob')
    return session, session.engine.state.player_by_id('ann')


def player(view, pid='ann'):
    return next(p for p in view['state']['players'] if p['id'] == pid)


def test_top_reveal_is_public_without_exposing_other_cards():
    session, ann = game()
    top = ann.library[-1]
    session.engine.state.reveal_card(top)
    for view in (session.view(perspective='ann'), session.view(perspective='bob'), session.observer_view()):
        assert [c['instance_id'] for c in view['state']['known_cards']] == [top.instance_id]
        assert view['state']['known_cards'][0]['library_position'] == 1
        assert [c['instance_id'] for c in player(view)['library']] == [top.instance_id]
    assert player(session.observer_view())['hand'] == []


def test_known_draw_is_face_up_but_hidden_zone_reentry_is_private():
    session, ann = game()
    top = ann.library[-1]
    session.engine.state.reveal_card(top)
    ann.draw()
    view = session.view(perspective='bob')
    assert [c['instance_id'] for c in player(view)['hand']] == [top.instance_id]
    assert player(view)['hand_count'] == len(ann.hand)
    assert player(view)['library'] == []
    ann.hand.remove(top)
    ann.add_to_zone(top, Zone.GRAVEYARD)
    ann.graveyard.remove(top)
    ann.add_to_zone(top, Zone.HAND)
    assert player(session.observer_view())['hand'] == []


def test_shuffle_invalidates_even_if_order_does_not_change(monkeypatch):
    session, ann = game()
    session.engine.state.reveal_card(ann.library[-1])
    monkeypatch.setattr('mtg_analyzer.models.game.player.random.shuffle', lambda items: None)
    ann.shuffle_library()
    view = session.observer_view()
    assert player(view)['library'] == []
    assert view['state']['known_cards'] == []
    ann.draw()
    assert player(session.observer_view())['hand'] == []


def test_private_reorder_does_not_expose_known_card_positions():
    session, ann = game()
    session.engine.state.reveal_card(ann.library[-1])
    ann.library.reverse()
    view = session.observer_view()
    assert view['state']['known_cards'] == []
    assert player(view)['library'] == []


def test_exact_library_positions_do_not_expose_gaps():
    session, ann = game()
    state = session.engine.state
    first, third = ann.library[-1], ann.library[-3]
    state.reveal_card(first)
    state.reveal_card(third)
    view = session.observer_view()
    assert {c['name']: c['library_position'] for c in view['state']['known_cards']} == {first.name: 1, third.name: 3}
    ann.draw()
    view = session.observer_view()
    assert [(c['name'], c['library_position']) for c in view['state']['known_cards'] if c['zone'] == 'library'] == [(third.name, 2)]
    assert len(player(view)['library']) == 1


def test_public_hand_reveal_and_private_look_are_different():
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.damage_draw import RevealHandChooseDiscardEffect
    session, ann = game()
    state = session.engine.state
    bob = state.player_by_id('bob')
    context = GameContext(state, session.engine.rules)
    for public in (False, True):
        state.pending_choice = None
        effect = RevealHandChooseDiscardEffect(source=ann.hand[0], reveal=public)
        effect.apply(context, [bob])
        assert len(player(session.observer_view(), 'bob')['hand']) == (len(bob.hand) if public else 0)


def test_clone_is_independent_and_undo_restores_knowledge():
    session, ann = game()
    state = session.engine.state
    state.reveal_card(ann.library[-1])
    clone = state.clone()
    assert clone.public_card_knowledge.view(clone)
    clone.player_by_id('ann').shuffle_library()
    assert clone.public_card_knowledge.view(clone) == []
    assert session.observer_view()['state']['known_cards']
    session._snapshot('test shuffle', 'ann')
    session.engine.rules.shuffle_library(ann)
    assert session.observer_view()['state']['known_cards'] == []
    session.rewind()
    assert session.observer_view()['state']['known_cards']


def test_feed_keeps_revealed_face_after_object_disappears():
    session, ann = game()
    state = session.engine.state
    obj = ann.library[-1]
    start = len(state.event_log)
    state.reveal_card(obj)
    ann.library.remove(obj)
    session.table_feed.announce_events(state, state.event_log[start:], 1)
    reveal = session.observer_view()['table_messages'][-1]
    assert reveal['card_id'] == obj.card.id
    assert reveal['revealed_card']['name'] == obj.name
    assert reveal['revealed_card']['instance_id'] == obj.instance_id


def test_multi_card_reveal_until_hand_preserves_both_known_cards():
    session, ann = game()
    expected = {obj.instance_id for obj in ann.library[-2:]}
    session.engine.rules.reveal_until_creature_type(ann, {'Bear'}, count=2, hit_destination='hand')
    assert {obj['instance_id'] for obj in player(session.observer_view())['hand']} == expected


def test_multi_pick_revealed_search_keeps_known_hand_after_remaining_library_shuffle():
    session, ann = game()
    expected = [ann.library[-1].instance_id, ann.library[-3].instance_id]
    session.engine.rules._finish_search(ann, expected, 'hand', reveal=True)
    view = session.observer_view()
    assert {obj['instance_id'] for obj in player(view)['hand']} == set(expected)
    assert player(view)['library'] == []


def test_private_order_choice_clears_even_if_the_order_is_unchanged():
    session, ann = game()
    state = session.engine.state
    top = ann.library[-1]
    state.reveal_card(top)
    session.engine.rules._finish_look_top(ann, 'scry', [], [top.instance_id])
    assert player(session.observer_view())['library'] == []
    assert session.observer_view()['state']['known_cards'] == []


def test_known_hand_identity_survives_turn_change_and_pruned_event_history():
    session, ann = game()
    obj = ann.hand[0]
    state = session.engine.state
    state.reveal_card(obj)
    state.internal_turn.number += 1
    clone = state.clone()
    assert not any(event.type == 'REVEAL' for event in clone.event_log)
    assert [card['instance_id'] for card in clone.public_card_knowledge.view(clone)] == [obj.instance_id]


def test_explicit_reveal_snapshot_also_handles_detached_batch_cards():
    session, ann = game()
    state = session.engine.state
    obj = ann.library.pop()
    start = len(state.event_log)
    state.reveal_card(obj, ann.id)
    session.table_feed.announce_events(state, state.event_log[start:], 1)
    reveal = session.observer_view()['table_messages'][-1]
    assert reveal['revealed_card']['card_id'] == obj.card.id
    assert reveal['revealed_card']['name'] == obj.name
    assert session.observer_view()['state']['known_cards'] == []


def test_announced_shuffle_also_invalidates_an_unchanged_order():
    session, ann = game()
    state = session.engine.state
    state.reveal_card(ann.library[-1])
    state.fire_event(GameEvent(EventType.SHUFFLE, player_id=ann.id))
    assert player(session.observer_view())['library'] == []
    assert session.observer_view()['state']['known_cards'] == []
