"""Untargeted firing-event copies retain last-known spell/ability decisions."""
import json

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.game_session import GameSession
from tests.test_mec112_copy_targets import _bolt, _choose
from tests.test_workingon_copy_cards import _named, _x_activation


def _cast_x_instant(*, watcher='Unbound Flourishing', caster='p1'):
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, watcher)
    spell = _named(engine, 'Volcanic Geyser', Zone.HAND, owner=caster)
    player = engine.state.player_by_id(caster)
    player.mana_pool.add_many({'R': 4, 'C': 12})
    engine.cast_spell(player, spell, x=2, targets=[engine.state.player_by_id('p2' if caster == 'p1' else 'p1')])
    engine.rules.put_triggers_on_stack()
    return engine, spell, engine.state.stack[0], engine.state.stack[-1]


def test_countered_x_spell_still_produces_the_original_copy():
    engine, spell, original, trigger = _cast_x_instant()
    engine.rules.counter_spell(spell)
    assert spell.zone == Zone.GRAVEYARD
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    _choose(engine, 'p3')
    copied = engine.state.stack[-1]
    assert copied.x == 2 and copied.obj.name == 'Volcanic Geyser'
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18
    assert engine.state.player_by_id('p2').life == 20


def test_live_original_target_changes_take_precedence_over_firing_recipe():
    engine, spell, original, trigger = _cast_x_instant()
    original.targets = [engine.state.player_by_id('p3')]
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('decline')
    assert engine.state.stack[-1].targets == [engine.state.player_by_id('p3')]


def test_departure_recipe_captures_changed_targets_before_countering():
    engine, spell, original, trigger = _cast_x_instant()
    original.targets = [engine.state.player_by_id('p3')]
    engine.rules.counter_spell(spell)
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18
    assert engine.state.player_by_id('p2').life == 20


def test_recasting_same_card_does_not_replace_original_recipe():
    engine, spell, original, trigger = _cast_x_instant()
    engine.rules.counter_spell(spell)
    engine.state.player_by_id('p1').graveyard.remove(spell)
    spell.zone = Zone.HAND
    engine.state.player_by_id('p1').hand.append(spell)
    engine.cast_spell(engine.state.player_by_id('p1'), spell, x=7,
                      targets=[engine.state.player_by_id('p3')])
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(engine.state.stack[-1])  # The new cast's trigger.
    engine.rules.counter_spell(spell)
    assert engine.state.stack == [trigger]
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('decline')
    assert engine.state.stack[-1].x == 2
    assert engine.state.stack[-1].targets == [engine.state.player_by_id('p2')]


def test_frozen_card_characteristics_survive_original_face_changes():
    engine, spell, original, trigger = _cast_x_instant()
    engine.rules.counter_spell(spell)
    spell.card = Card(id='changed', name='Other Face', type_line='Creature — Dragon',
                      is_creature=True, power=7, toughness=7)
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('decline')
    copied = engine.state.stack[-1]
    assert copied.obj.name == 'Volcanic Geyser' and copied.obj.card.is_instant


def test_countered_x_ability_is_copied_with_source_and_original_x():
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Unbound Flourishing')
    source = _x_activation(engine)
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 2)
    engine.activate_ability(player, source, 0, x=2, targets=[engine.state.player_by_id('p2')])
    original = engine.state.stack[-1]
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(original)
    source.x_paid = 9
    engine.rules.resolve_top_of_stack()
    _choose(engine, 'p3')
    assert engine.state.stack[-1].source is source and engine.state.stack[-1].x == 2
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18


def test_rings_can_copy_countered_ability_after_payment():
    engine, _ = _bolt()
    engine.state.stack = []
    _named(engine, 'Rings of Brighthearth')
    source = _x_activation(engine, '{1}')
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 3)
    engine.activate_ability(player, source, 0, x=2, targets=[engine.state.player_by_id('p2')])
    original = engine.state.stack[-1]
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(original)
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'pay_cost_then'
    engine.rules.resolve_choice('pay')
    _choose(engine, 'p3')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18


def test_wandering_archaic_recipe_survives_tax_and_optional_copy_choices():
    engine, spell, original, trigger = _cast_x_instant(watcher='Wandering Archaic', caster='p2')
    engine.rules.counter_spell(spell)
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'pay_cost_then'
    engine.rules.resolve_choice('decline')
    assert engine.state.pending_choice['kind'] == 'composite_optional'
    engine.rules.resolve_choice('yes')
    _choose(engine, 'p3')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p3').life == 18


def test_rewind_reconnects_frozen_recipe_targets_to_restored_state():
    engine, spell, original, trigger = _cast_x_instant()
    engine.rules.counter_spell(spell)
    engine.rules.resolve_top_of_stack()
    session = GameSession(engine, mode='replay', require_setup=False)
    json.dumps(session.view())
    session.apply_action({'type': 'decline'})
    session.rewind()
    restored = session.engine
    option = next(o['id'] for o in restored.state.pending_choice['options'] if o.get('player_id') == 'p3')
    session.apply_action({'type': 'choose', 'option_id': option})
    assert restored.state.player_by_id('p3').life == 18
    assert engine.state.player_by_id('p3').life == 20


def test_targeted_copy_cannot_use_a_registered_departed_recipe():
    engine, spell, original, trigger = _cast_x_instant()
    engine.rules.counter_spell(spell)
    assert original.stack_id in engine.state.copiable_stack_recipes
    assert engine.rules.copy_spell(original, 'p1', choose_new_targets=True) == []
    assert engine.rules.copy_spell(spell, 'p1', choose_new_targets=True) == []


def test_demonstrate_can_copy_countered_original_with_original_controller():
    from mtg_analyzer.game.effects.stack import DemonstrateCopyEffect

    engine, _ = _bolt()
    engine.state.stack = []
    spell = _named(engine, 'Lightning Bolt', Zone.HAND)
    spell.intrinsic_keywords.add('demonstrate')
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('R', 1)
    engine.cast_spell(player, spell, targets=[engine.state.player_by_id('p2')])
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(spell)
    spell.controller_id = 'p2'  # A departed original's current controller must not own its old trigger.
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['player_id'] == 'p1'
    engine.rules.resolve_choice('yes')
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    assert engine.state.pending_choice['player_id'] == 'p1'
    engine.rules.resolve_choice('decline')
    while not engine.state.pending_choice and engine.rules.resume_deferred_effects():
        pass
    assert engine.state.pending_choice['kind'] == 'demonstrate_opponent'
    engine.rules.resolve_choice('p3')
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 14


def test_wandering_archaic_controller_can_decline_copy_of_countered_spell():
    engine, spell, original, trigger = _cast_x_instant(watcher='Wandering Archaic', caster='p2')
    engine.rules.counter_spell(spell)
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('decline')
    assert engine.state.pending_choice['player_id'] == 'p1'
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert not engine.state.stack
    assert all(p.life == 20 for p in engine.state.players)
