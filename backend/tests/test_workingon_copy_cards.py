"""Printed copy-card requirements adjoining the shared MEC-112 target rounds."""
import pytest

from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.stack import DemonstrateCopyEffect
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec
from tests.test_mec112_copy_targets import _bolt, _creature, _choose, _choose_object
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.config import DB_PATH


def _named(engine, name, zone=Zone.BATTLEFIELD, owner='p1'):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def test_display_of_power_is_a_legal_copy_target_but_no_copy_is_created():
    engine, original = _bolt()
    spell = _named(engine, 'Display of Power', Zone.HAND)
    player = engine.state.player_by_id('p1')
    player.mana_pool.add_many({'R': 2, 'C': 1})
    engine.cast_spell(player, spell, targets=[original.obj])
    display = engine.state.stack[-1]
    before = list(engine.state.stack)
    assert engine.rules.copy_spell(display, 'p2', choose_new_targets=True) == []
    assert engine.rules.copy_spell(display, 'p2', new_targets=[original.obj]) == []
    assert engine.rules.copy_self_spell(spell, 'p2', choose_new_targets=True) is None
    assert engine.state.stack == before and not engine.state.pending_choice
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 14


@pytest.mark.parametrize('triggered', [False, True])
def test_return_the_favor_copies_activated_and_triggered_abilities_with_new_targets(triggered):
    engine, _ = _bolt()
    source = _creature(engine, 'Ability source')
    source.controller_id = 'p2'
    ability = StackItem(kind='ability', controller_id='p2', source=source,
        effects=build_effects([EffectSpec('damage', {'amount': 2, 'target_kind': 'player'})], source),
        targets=[engine.state.player_by_id('p1')],
        trigger_event={'instance_id': source.instance_id} if triggered else None,
        category='triggered' if triggered else 'activated')
    engine.state.stack = [ability]
    player = engine.state.player_by_id('p1')
    spell = _named(engine, 'Return the Favor', Zone.HAND)
    player.mana_pool.add_many({'R': 2, 'C': 1})
    engine.cast_spell(player, spell, mode=0, targets=[ability])
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    _choose(engine, 'p3')
    copied = engine.state.stack[-1]
    assert copied.kind == 'ability' and copied.source is source
    assert copied.controller_id == 'p1' and copied.trigger_event == ability.trigger_event
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18
    assert player.life == 18


def _x_activation(engine, cost='{X}', *, owner='p1'):
    source = _creature(engine, 'X source', owner)
    ability = bind_ability(AbilitySpec('activated', [EffectSpec('damage', {
        'amount': 'x', 'target_kind': 'player',
    })], cost={'text': cost}), source)
    source.activated_abilities.append(ability)
    return source


@pytest.mark.parametrize('cost,x', [('{X}', 2), ('{X}', 0)])
def test_unbound_flourishing_copies_the_announced_x_ability_and_offers_new_targets(cost, x):
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    source = _x_activation(engine, cost)
    source.counters['charge'] = 4
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 4)
    engine.activate_ability(player, source, 0, x=x, targets=[engine.state.player_by_id('p2')])
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2
    source.x_paid = 9
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    _choose(engine, 'p3')
    assert engine.state.stack[-1].x == x and engine.state.stack[-1].source is source
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 20 - x
    assert engine.state.player_by_id('p3').life == 20 - x


def test_unbound_does_not_trigger_for_opponents_or_costs_without_x():
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    source = _x_activation(engine, '{X}', owner='p2')
    player = engine.state.player_by_id('p2')
    player.mana_pool.add('C', 3)
    engine.activate_ability(player, source, 0, x=3, targets=[engine.state.player_by_id('p1')])
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1
    engine.state.stack = []
    source = _x_activation(engine, '{1}', owner='p1')
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 1)
    engine.activate_ability(player, source, 0, x=3, targets=[engine.state.player_by_id('p2')])
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 1


def test_demonstrate_controller_chooses_opponent_after_own_targets():
    engine, original = _bolt()
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    _choose(engine, 'p3')
    assert len(engine.state.stack) == 2
    engine.rules.resume_deferred_effects()
    assert engine.state.pending_choice['kind'] == 'demonstrate_opponent'
    assert engine.state.pending_choice['player_id'] == 'p1'
    with pytest.raises(ValueError):
        engine.rules.resolve_choice('p1')
    engine.rules.resolve_choice('p3')
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    assert engine.state.pending_choice['player_id'] == 'p3'
    _choose(engine, 'p1')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p1').life == 17
    assert engine.state.player_by_id('p2').life == 17
    assert engine.state.player_by_id('p3').life == 17


def test_demonstrate_with_uncopyable_spell_never_asks_for_an_opponent():
    engine, _ = _bolt()
    spell = _named(engine, 'Display of Power', Zone.HAND)
    engine.state.player_by_id('p1').hand.remove(spell)
    spell.zone = Zone.STACK
    item = StackItem(kind='spell', controller_id='p1', obj=spell)
    engine.state.stack = [item]
    DemonstrateCopyEffect(source=spell).apply(engine.rules.context)
    assert engine.state.stack == [item] and not engine.state.pending_choice
    assert not engine.state.deferred_effects


def test_demonstrate_ward_triggers_wait_above_both_sequential_copies():
    engine, original = _bolt()
    warded = _creature(engine, 'Warded', 'p2')
    warded.parametric_keywords = {'ward': {'cost': '{2}'}}
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    _choose_object(engine, warded)
    own_copy = engine.state.stack[-1]
    assert own_copy.kind == 'spell' and len(engine.state.stack) == 2
    engine.rules.resume_deferred_effects()
    engine.rules.resolve_choice('p3')
    _choose_object(engine, warded)
    for _ in range(5):
        if not engine.rules.resume_deferred_effects():
            break
    assert engine.state.stack[:2] == [original, own_copy]
    assert engine.state.stack[2].kind == 'spell'
    assert len(engine.state.stack) == 5
    assert all(i.kind == 'ability' for i in engine.state.stack[3:])


@pytest.mark.parametrize('counter_cost', ['any', 'x'])
def test_unbound_does_not_treat_variable_counter_cost_as_mana_symbol_x(counter_cost):
    from mtg_analyzer.game.costs import REMOVE_COUNTERS_ANY

    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    source = _creature(engine, 'Counter source')
    source.counters['charge'] = 3
    ability = bind_ability(AbilitySpec('activated', [EffectSpec('damage', {
        'amount': 1, 'target_kind': 'player',
    })], cost=({'remove_counters': ['charge', REMOVE_COUNTERS_ANY]} if counter_cost == 'any'
               else {'text': 'Remove X charge counters from this'})), source)
    source.activated_abilities.append(ability)
    player = engine.state.player_by_id('p1')
    engine.activate_ability(player, source, 0, x=2, targets=[engine.state.player_by_id('p2')])
    engine.rules.put_triggers_on_stack()
    assert source.counters['charge'] == 1
    assert len(engine.state.stack) == 1


def test_unbound_instant_or_sorcery_gets_only_its_copy_trigger():
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    spell = _named(engine, 'Blaze', Zone.HAND)
    assert spell.spell_effects
    player = engine.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 2, 'R': 1})
    engine.cast_spell(player, spell, x=2, targets=[engine.state.player_by_id('p2')])
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2  # No extra permanent-X trigger for a sorcery.
    engine.rules.resolve_top_of_stack()
    _choose(engine, 'p3')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == engine.state.player_by_id('p3').life == 18


def test_unbound_repeated_x_activation_uses_each_stack_items_own_value():
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    source = _x_activation(engine)
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 5)
    engine.activate_ability(player, source, 0, x=3, targets=[engine.state.player_by_id('p2')])
    engine.resolve_until_stable()
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 14
    engine.activate_ability(player, source, 0, x=1, targets=[engine.state.player_by_id('p2')])
    engine.resolve_until_stable()
    _choose(engine, 'p3')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 13
    assert engine.state.player_by_id('p3').life == 19


def test_demonstrate_session_rewind_restores_selected_opponent_and_pending_targets():
    from mtg_analyzer.services.game_session import GameSession

    engine, original = _bolt()
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    session = GameSession(engine, mode='replay', require_setup=False)
    session.apply_action({'type': 'decline'})
    assert session.engine.state.pending_choice['kind'] == 'demonstrate_opponent'
    session.apply_action({'type': 'choose', 'option_id': 'p3'})
    assert session.engine.state.pending_choice['player_id'] == 'p3'
    session.apply_action({'type': 'decline'})
    assert session.engine.state.player_by_id('p2').life == 11
    session.rewind()
    restored = session.engine
    assert restored is not engine
    assert restored.state.pending_choice['kind'] == 'copy_targets'
    assert restored.state.pending_choice['player_id'] == 'p3'
    option = next(o['id'] for o in restored.state.pending_choice['options'] if o.get('player_id') == 'p1')
    session.apply_action({'type': 'choose', 'option_id': option})
    assert restored.state.player_by_id('p1').life == 17
    assert restored.state.player_by_id('p2').life == 14


def test_demonstrate_preserves_ward_controller_and_cost_from_first_copy_entry():
    engine, original = _bolt()
    warded = _creature(engine, 'Warded', 'p2')
    warded.parametric_keywords = {'ward': {'cost': '{2}'}}
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    _choose_object(engine, warded)
    own = engine.state.stack[-1]
    assert own.deferred_ward_triggers[0].controller_id == 'p2'
    warded.controller_id = 'p3'
    warded.parametric_keywords = {'ward': {'cost': '{9}'}}
    engine.rules.resume_deferred_effects()
    engine.rules.resolve_choice('p3')
    engine.rules.resolve_choice('decline')
    while engine.rules.resume_deferred_effects():
        pass
    assert engine.state.stack[-1].controller_id == 'p2'
    assert '{2}' in engine.state.stack[-1].description
    assert len(engine.state.stack) == 4  # Two copies, original, and the captured ward.


def test_demonstrate_refuses_an_opponent_who_has_left_during_the_choice():
    engine, original = _bolt()
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    engine.rules.resolve_choice('decline')
    engine.rules.resume_deferred_effects()
    engine.state.player_by_id('p3').has_lost = True
    with pytest.raises(ValueError, match='living opponent'):
        engine.rules.resolve_choice('p3')
    assert engine.state.pending_choice['kind'] == 'demonstrate_opponent'
    engine.rules.resolve_choice('p2')
    assert engine.state.pending_choice['player_id'] == 'p2'


def test_demonstrate_finishes_captured_wards_when_original_spell_leaves():
    engine, original = _bolt()
    warded = _creature(engine, 'Warded', 'p3')
    warded.parametric_keywords = {'ward': {'cost': '{2}'}}
    DemonstrateCopyEffect(source=original.obj).apply(engine.rules.context)
    _choose_object(engine, warded)
    own = engine.state.stack[-1]
    engine.state.stack.remove(original)
    original.obj.zone = Zone.GRAVEYARD
    while engine.rules.resume_deferred_effects():
        pass
    assert not engine.state.pending_choice
    assert engine.state.stack[0] is own and engine.state.stack[1].kind == 'ability'
    assert own.deferred_ward_triggers == [] and not own.ward_check_deferred
