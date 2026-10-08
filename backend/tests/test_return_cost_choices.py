"""Returning an Elf for Wirewood Symbiote is an announced cost choice."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.costs import ActivationCost
from mtg_analyzer.game.effects.core import ActivatedAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession


def position():
    engine = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = 'main1'

    def permanent(name, subtype, controller='p1', oracle=''):
        card = Card(id=name, name=name, type_line=f'Creature — {subtype}',
                    is_creature=True, power=1, toughness=1, oracle_text=oracle)
        obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
        engine.state.add_to_battlefield(obj)
        bind_from_catalogue(obj)
        return obj

    source = permanent('Wirewood Symbiote', 'Insect', oracle=(
        "Return an Elf you control to its owner's hand: Untap target creature. "
        'Activate only once each turn.'))
    first = permanent('First Elf', 'Elf')
    second = permanent('Second Elf', 'Elf')
    foreign = permanent('Opponent Elf', 'Elf', 'p2')
    first.tapped = True
    engine.recompute_continuous_effects()
    return engine, engine.state.active_player, source, first, second, foreign


def test_wirewood_offer_has_separate_target_and_return_cost_pools():
    engine, player, source, first, second, foreign = position()
    action = next(a for a in engine.legal_actions(player)
                  if a['type'] == 'activate_ability' and a['instance_id'] == source.instance_id)
    assert action['requires_target']
    assert action['return_cost']['count'] == 1
    assert {o['instance_id'] for o in action['return_cost']['options']} == {first.instance_id, second.instance_id}


def test_wirewood_session_returns_selected_second_elf_then_untaps_target():
    engine, player, source, first, second, _ = position()
    session = GameSession(engine, mode='replay', require_setup=False)
    session.apply_action({'type': 'activate_ability', 'instance_id': source.instance_id,
                          'targets': [{'instance_id': first.instance_id}],
                          'return_choices': [second.instance_id]})
    assert second.zone == Zone.HAND
    assert first.zone == Zone.BATTLEFIELD
    assert first.tapped
    assert len(engine.state.stack) == 1
    engine.rules.resolve_top_of_stack()
    assert not first.tapped
    assert not engine.can_activate(player, source, source.activated_abilities[0])


@pytest.mark.parametrize('bad_pick', ['empty', 'too_many', 'duplicate', 'foreign', 'nonelf', 'missing', 'left_zone'])
def test_invalid_return_choice_does_not_pay_or_stack(bad_pick):
    engine, player, source, first, second, foreign = position()
    picks = {'empty': [], 'too_many': [first.instance_id, second.instance_id],
             'duplicate': [second.instance_id, second.instance_id],
             'foreign': [foreign.instance_id], 'nonelf': [source.instance_id],
             'missing': [999999], 'left_zone': [second.instance_id]}[bad_pick]
    if bad_pick == 'left_zone':
        engine.rules.return_to_hand(second)
    ability = source.activated_abilities[0]
    assert not engine.can_activate(player, source, ability, return_choices=picks)
    with pytest.raises(ValueError):
        engine.activate_ability(player, source, targets=[first], return_choices=picks)
    assert first.zone == Zone.BATTLEFIELD and first.tapped
    assert not engine.state.stack
    assert ability._last_activated_turn != engine.state.internal_turn.number


def test_counted_return_cost_uses_selected_permanents():
    engine, player, source, first, second, _ = position()
    source.activated_abilities = [ActivatedAbility(source=source, effects=[],
        cost=ActivationCost(return_to_hand_count=(1, 'creature')))]
    engine.activate_ability(player, source, return_choices=[second.instance_id])
    assert second.zone == Zone.HAND
    assert first.zone == Zone.BATTLEFIELD


def test_noninteractive_return_cost_keeps_first_match_fallback():
    engine, player, source, first, second, _ = position()
    engine.activate_ability(player, source, targets=[second])
    assert first.zone == Zone.HAND
    assert second.zone == Zone.BATTLEFIELD


def test_wirewood_rewind_allows_a_different_return_choice():
    engine, player, source, first, second, _ = position()
    session = GameSession(engine, mode='replay', require_setup=False)
    action = {'type': 'activate_ability', 'instance_id': source.instance_id,
              'targets': [{'instance_id': first.instance_id}],
              'return_choices': [second.instance_id]}
    session.apply_action(action)
    session.rewind()
    session.apply_action({**action, 'return_choices': [first.instance_id]})
    assert session.engine.state.find_object(first.instance_id).zone == Zone.HAND
    assert session.engine.state.find_object(second.instance_id).zone == Zone.BATTLEFIELD
