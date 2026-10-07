"""Jump Scare: announced targets and exile costs retain their identities."""
import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.game.catalogue.cards.test_jump_scare_deck import _game, _card, _filler, _answer_all


def _choice_setup(players=3):
    engine = _game(players=players)
    player = engine.state.players[0]
    spell = _card(engine, 'Disorienting Choice', zone=Zone.HAND)
    engine.state.current_step = 'main1'
    player.mana_pool.add_many({'G': 1, 'C': 3})
    rocks = [_filler(engine, f'Rock{i}', 'Artifact', player=f'p{i}') for i in range(2, players+1)]
    return engine, player, spell, rocks


@pytest.mark.parametrize('keyword', ['Hexproof', 'Protection from green'])
def test_choice_cannot_target_protected_opponents_permanent(keyword):
    engine, player, spell, rocks = _choice_setup()
    if keyword.startswith('Protection'):
        rocks[0].card.oracle_text = keyword
    else:
        rocks[0].intrinsic_keywords.add(keyword.lower())
    mana = player.mana_pool.total()
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=rocks)
    assert spell.zone == Zone.HAND and player.mana_pool.total() == mana


def test_choice_allows_declining_an_opponents_round():
    engine, player, spell, rocks = _choice_setup()
    engine.cast_spell(player, spell, targets=rocks[1:])
    assert engine.state.pending_choice is None
    engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id'] == 'p3'
    engine.resolve_pending_choice('decline')
    _answer_all(engine)
    assert len([o for o in engine.state.battlefield if o.is_land and o.controller_id == 'p1']) == 1


def test_choice_rejects_two_targets_from_one_opponent_before_payment():
    engine, player, spell, rocks = _choice_setup()
    extra = _filler(engine, 'Extra', 'Enchantment', player='p2')
    with pytest.raises(ValueError, match='one legal target per player'):
        engine.cast_spell(player, spell, targets=[rocks[0], extra])
    assert player.mana_pool.total() == 4


def test_choice_partial_illegality_skips_only_illegal_target_and_its_count():
    engine, player, spell, rocks = _choice_setup()
    engine.cast_spell(player, spell, targets=rocks)
    rocks[0].intrinsic_keywords.add('hexproof')
    engine.resolve_until_stable()
    assert engine.state.pending_choice['player_id'] == 'p3'
    engine.resolve_pending_choice('decline')
    _answer_all(engine)
    assert len([o for o in engine.state.battlefield if o.is_land and o.controller_id == 'p1']) == 1


def test_choice_no_targets_resolves_without_exile_or_search():
    engine, player, spell, rocks = _choice_setup()
    engine.cast_spell(player, spell, targets=[])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert not [o for o in engine.state.battlefield if o.is_land]


def _mist_setup():
    engine = _game()
    player = engine.state.players[0]
    mist = _card(engine, 'Primordial Mist')
    hidden = [_filler(engine, f'Hidden{i}', 'Creature', mv=1, power=1, toughness=1) for i in range(2)]
    for obj in hidden:
        engine.rules.turn_face_down(obj, 'manifest')
    engine.state.current_step = 'main1'
    return engine, player, mist, hidden


def test_mist_chosen_permanent_is_exiled_face_up_before_any_response():
    engine, player, mist, hidden = _mist_setup()
    engine.activate_ability(player, mist, 0, tap_choices=[hidden[1].instance_id])
    assert hidden[0].zone == Zone.BATTLEFIELD and hidden[0].face_down
    assert hidden[1].zone == Zone.EXILE and not hidden[1].face_down
    assert hidden[1].instance_id not in engine.state.temp_play_permissions
    engine.rules.counter_ability(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert hidden[1].zone == Zone.EXILE
    assert hidden[1].instance_id not in engine.state.temp_play_permissions


@pytest.mark.parametrize('invalid', ['face_up', 'foreign', 'duplicate'])
def test_mist_rejects_invalid_cost_selection_before_exiling(invalid):
    engine, player, mist, hidden = _mist_setup()
    if invalid == 'face_up':
        engine.rules.turn_face_up(hidden[1])
    elif invalid == 'foreign':
        hidden[1].controller_id = 'p2'
    choices = [hidden[1].instance_id] * (2 if invalid == 'duplicate' else 1)
    with pytest.raises(ValueError):
        engine.activate_ability(player, mist, 0, tap_choices=choices)
    assert all(obj.zone == Zone.BATTLEFIELD for obj in hidden)


def test_mist_two_activations_grant_only_their_own_exiled_card():
    engine, player, mist, hidden = _mist_setup()
    first = engine.activate_ability(player, mist, 0, tap_choices=[hidden[0].instance_id])
    engine.activate_ability(player, mist, 0, tap_choices=[hidden[1].instance_id])
    engine.rules.resolve_top_of_stack()
    assert hidden[1].instance_id in engine.state.temp_play_permissions
    assert hidden[0].instance_id not in engine.state.temp_play_permissions
    engine.rules.counter_ability(first)
    engine.resolve_until_stable()
    assert hidden[0].instance_id not in engine.state.temp_play_permissions


def test_mist_permission_does_not_follow_card_that_left_and_reentered_exile():
    engine, player, mist, hidden = _mist_setup()
    engine.activate_ability(player, mist, 0, tap_choices=[hidden[1].instance_id])
    engine.rules.return_to_hand(hidden[1])
    engine.rules.exile(hidden[1])
    engine.resolve_until_stable()
    assert hidden[1].instance_id not in engine.state.temp_play_permissions


def test_mist_cost_picker_and_session_rewind_restore_chosen_identity():
    engine, player, mist, hidden = _mist_setup()
    action = next(a for a in engine.legal_actions(player) if a.get('instance_id') == mist.instance_id)
    assert {o['instance_id'] for o in action['exile_cost']['options']} == {o.instance_id for o in hidden}
    session = GameSession(engine)
    session.apply_action({'type': 'activate_ability', 'instance_id': mist.instance_id, 'ability_index': 0,
                          'tap_choices': [hidden[1].instance_id]})
    assert session.engine.state.find_object(hidden[1].instance_id).zone == Zone.EXILE
    session.rewind()
    assert all(session.engine.state.find_object(o.instance_id).zone == Zone.BATTLEFIELD for o in hidden)
