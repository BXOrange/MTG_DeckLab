"""RULE 707.10c: copied targets are chosen before the copies enter the stack."""
import copy

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase
from tests.test_hideaway_keyword import _game


def _bolt():
    engine, *_ = _game(available=8)
    obj = GameObject(CardDatabase(DB_PATH).get_card('Lightning Bolt'), owner_id='p1', zone=Zone.STACK)
    bind_from_catalogue(obj)
    victim = engine.state.player_by_id('p2')
    item = StackItem(kind='spell', controller_id='p1', obj=obj,
                     effects=obj.spell_effects, targets=[victim])
    engine.state.stack.append(item)
    return engine, item


def _choose(engine, player_id):
    choice = engine.state.pending_choice
    option = next(o for o in choice['options'] if o.get('player_id') == player_id)
    engine.rules.resolve_choice(option['id'])


def test_multiple_copies_wait_for_all_target_choices():
    engine, original = _bolt()
    copies = engine.rules.copy_spell(original, 'p1', 2, choose_new_targets=True)
    assert engine.state.stack == [original]
    _choose(engine, 'p3')
    assert engine.state.stack == [original]
    engine.rules.resolve_choice('decline')
    assert engine.state.stack == [original, *copies]
    assert copies[0].targets == [engine.state.player_by_id('p3')]
    assert copies[1].targets == original.targets
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_top_of_stack()
    assert engine.state.player_by_id('p2').life == 17
    assert engine.state.player_by_id('p3').life == 17


def test_no_permission_and_forced_targets_do_not_offer_retargeting():
    engine, original = _bolt()
    copies = engine.rules.copy_spell(original, 'p3')
    assert not engine.state.pending_choice
    assert copies[0].targets == original.targets
    forced = engine.rules.copy_spell(original, 'p1', new_targets=[engine.state.player_by_id('p3')],
                                     choose_new_targets=True)
    assert not engine.state.pending_choice
    assert forced[0].targets == [engine.state.player_by_id('p3')]


def test_invalid_choice_can_be_retried_and_pending_state_is_copyable():
    engine, original = _bolt()
    engine.rules.copy_spell(original, 'p1', choose_new_targets=True)
    with pytest.raises(ValueError):
        engine.rules.resolve_choice('not-a-target')
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    snapshot = copy.deepcopy(engine.state)
    assert snapshot.pending_stack_copies[0]['item'] is not engine.state.pending_stack_copies[0]['item']
    _choose(engine, 'p3')
    assert not engine.state.pending_stack_copies


def test_copy_ability_keeps_source_and_trigger_snapshot():
    engine, original = _bolt()
    source = original.obj
    ability = StackItem(kind='ability', controller_id='p1', source=source,
                        effects=build_effects([EffectSpec('damage', {'amount': 2, 'target_kind': 'any'})], source),
                        targets=original.targets, trigger_event={'instance_id': 123}, ability_key='test')
    engine.state.stack.append(ability)
    copied = engine.rules.copy_ability(ability, 'p3', choose_new_targets=True)
    assert copied not in engine.state.stack
    _choose(engine, 'p1')
    assert copied.source is source
    assert copied.effects[0] is not ability.effects[0]
    assert copied.trigger_event == ability.trigger_event
    assert copied.ability_key == ability.ability_key
    engine.rules.resolve_top_of_stack()
    assert engine.state.player_by_id('p1').life == 18


def test_self_copy_does_not_offer_resolving_original_as_a_stack_target():
    engine, original = _bolt()
    engine.state.stack.remove(original)
    engine.rules.context.resolving_stack_item = original
    copied = engine.rules.copy_self_spell(original.obj, 'p1', choose_new_targets=True)
    assert engine.state.stack == []
    assert copied not in engine.state.stack
    _choose(engine, 'p3')
    assert engine.state.stack == [copied]


def test_copy_self_constructor_accepts_sealed_permission():
    engine, original = _bolt()
    effect = build_effects([EffectSpec('copy_self_spell', {})], original.obj,
                           copy_targets_text='You may choose new targets for the copy.')[0]
    assert effect.choose_new_targets


def _creature(engine, name, owner='p1', toughness=2):
    obj = GameObject(Card(id=name, name=name, type_line='Creature — Bear',
                          is_creature=True, power=2, toughness=toughness),
                     owner_id=owner, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(obj)
    return obj


def _choose_object(engine, obj):
    option = next(o for o in engine.state.pending_choice['options']
                  if o.get('instance_id') == obj.instance_id)
    engine.rules.resolve_choice(option['id'])


def test_plural_target_swap_requires_distinct_completion():
    engine, original = _bolt()
    a, b = _creature(engine, 'A'), _creature(engine, 'B')
    original.targets = [a, b]
    original.target_incarnations = [a.zone_incarnation, b.zone_incarnation]
    original.effects = build_effects([EffectSpec('destroy', {'target_kind': 'creature', 'count': 2})], original.obj)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    _choose_object(engine, b)
    choice = engine.state.pending_choice
    assert not choice['optional']
    assert not any(o['id'] in ('decline', 'keep') for o in choice['options'])
    _choose_object(engine, a)
    assert copied.targets == [b, a]
    engine.rules.resolve_top_of_stack()
    assert a.zone == b.zone == Zone.GRAVEYARD


def test_illegal_original_target_can_be_kept_but_does_not_resolve_on_new_incarnation():
    engine, original = _bolt()
    victim = _creature(engine, 'Victim')
    original.targets = [victim]
    original.target_incarnations = [victim.zone_incarnation]
    engine.state.remove_from_battlefield(victim)
    victim.zone = Zone.EXILE
    victim.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(victim)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    engine.rules.resolve_choice('decline')
    assert copied.targets == [victim]
    engine.rules.resolve_top_of_stack()
    assert victim.damage_marked == 0


def test_chain_of_smog_target_player_may_decline_copy():
    engine, original = _bolt()
    obj = GameObject(CardDatabase(DB_PATH).get_card('Chain of Smog'), owner_id='p1', zone=Zone.STACK)
    bind_from_catalogue(obj)
    engine.state.stack = [StackItem(kind='spell', controller_id='p1', obj=obj,
                                   effects=obj.spell_effects, targets=original.targets)]
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['kind'] == 'composite_optional'
    assert engine.state.pending_choice['player_id'] == 'p2'
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert not engine.state.stack
    assert obj.zone == Zone.GRAVEYARD


def test_chain_of_smog_copy_can_change_target_then_stop_chain():
    engine, original = _bolt()
    obj = GameObject(CardDatabase(DB_PATH).get_card('Chain of Smog'), owner_id='p1', zone=Zone.STACK)
    bind_from_catalogue(obj)
    engine.state.stack = [StackItem(kind='spell', controller_id='p1', obj=obj,
                                   effects=obj.spell_effects, targets=original.targets)]
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice('yes')
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    assert engine.state.pending_choice['player_id'] == 'p2'
    _choose(engine, 'p3')
    assert engine.state.stack[-1].controller_id == 'p2'
    engine.rules.resolve_top_of_stack()
    assert engine.state.pending_choice['player_id'] == 'p3'
    engine.rules.resolve_choice('decline')
    engine.resolve_until_stable()
    assert not engine.state.stack


def test_sevinne_copy_retargets_after_first_return_without_recursing():
    engine, _ = _bolt()
    player = engine.state.player_by_id('p1')
    first, second = _creature(engine, 'First'), _creature(engine, 'Second')
    for obj in (first, second):
        engine.state.remove_from_battlefield(obj)
        obj.zone = Zone.GRAVEYARD
        player.graveyard.append(obj)
    spell = GameObject(CardDatabase(DB_PATH).get_card("Sevinne's Reclamation"),
                       owner_id='p1', zone=Zone.STACK)
    bind_from_catalogue(spell)
    spell.cast_via_flashback = True
    engine.state.stack = [StackItem(kind='spell', controller_id='p1', obj=spell,
                                   effects=spell.spell_effects, targets=[first])]
    engine.rules.resolve_top_of_stack()
    assert first in engine.state.battlefield and second in player.graveyard
    assert spell.zone == Zone.STACK
    engine.rules.resolve_choice('yes')
    assert engine.state.pending_choice['kind'] == 'copy_targets'
    _choose_object(engine, second)
    copied = engine.state.stack[-1]
    assert not copied.obj.cast_via_flashback
    engine.resolve_until_stable()
    assert second in engine.state.battlefield
    assert spell.zone == Zone.EXILE
    assert not engine.state.pending_choice and not engine.state.stack


def test_copied_ability_uses_its_controller_for_new_target_restrictions():
    engine, original = _bolt()
    their_bear = _creature(engine, 'Their Bear', 'p2')
    my_bear = _creature(engine, 'My Bear', 'p1')
    ability = StackItem(kind='ability', controller_id='p1', source=original.obj,
                        effects=build_effects([EffectSpec('add_counters', {
                            'counter_type': '+1/+1', 'count': 1,
                            'target_kind': 'creature_you_control',
                        })], original.obj), targets=[my_bear])
    engine.state.stack.append(ability)
    copied = engine.rules.copy_ability(ability, 'p2', choose_new_targets=True)
    choice = engine.state.pending_choice
    assert any(o.get('instance_id') == their_bear.instance_id for o in choice['options'])
    engine.rules.resolve_choice('decline')
    engine.rules.resolve_top_of_stack()
    assert not my_bear.counters
    assert copied.source is original.obj


def test_ward_triggers_are_above_all_finalized_copies():
    engine, original = _bolt()
    warded = _creature(engine, 'Warded', 'p2')
    warded.parametric_keywords = {'ward': {'cost': '{2}'}}
    copies = engine.rules.copy_spell(original, 'p1', 2, choose_new_targets=True)
    _choose_object(engine, warded)
    assert engine.state.stack == [original]
    _choose_object(engine, warded)
    stack = engine.state.stack
    assert stack[1:3] == copies
    assert len(stack) == 5
    assert all(item.kind == 'ability' for item in stack[3:])


def test_stale_kept_target_does_not_trigger_new_incarnations_ward():
    engine, original = _bolt()
    target = _creature(engine, 'Warded', 'p2')
    original.targets = [target]
    original.target_incarnations = [target.zone_incarnation]
    engine.state.remove_from_battlefield(target)
    target.zone = Zone.EXILE
    target.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(target)
    target.parametric_keywords = {'ward': {'cost': '{2}'}}
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    engine.rules.resolve_choice('decline')
    assert engine.state.stack == [original, copied]


def _blink(engine, obj):
    engine.state.remove_from_battlefield(obj)
    obj.zone = Zone.EXILE
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)


def test_copy_with_one_blinked_target_only_destroys_the_other_target():
    engine, original = _bolt()
    first, second = _creature(engine, 'First'), _creature(engine, 'Second')
    original.targets = [first, second]
    original.target_incarnations = [first.zone_incarnation, second.zone_incarnation]
    original.effects = build_effects([EffectSpec('destroy', {'target_kind': 'creature', 'count': 2})], original.obj)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    if engine.state.pending_choice:
        engine.rules.resolve_choice('decline')
    _blink(engine, first)
    engine.rules.resolve_top_of_stack()
    assert first.zone == Zone.BATTLEFIELD
    assert second.zone == Zone.GRAVEYARD
    assert copied.targets == [first, second]  # Masked resolution does not rewrite its choices.


def test_same_object_can_be_illegal_for_one_target_occurrence_and_legal_for_another():
    engine, original = _bolt()
    target = _creature(engine, 'Target')
    original.effects = build_effects([
        EffectSpec('damage', {'amount': 10, 'target_kind': 'creature_you_control'}),
        EffectSpec('add_counters', {'counter_type': '+1/+1', 'count': 1, 'target_kind': 'creature'}),
    ], original.obj)
    original.targets = [target, target]
    original.target_groups = [[target], [target]]
    original.target_incarnations = [target.zone_incarnation] * 2
    engine.rules.copy_spell(original, 'p1', choose_new_targets=True)
    if engine.state.pending_choice:
        engine.rules.resolve_choice('decline')
    target.controller_id = 'p2'
    engine.rules.resolve_top_of_stack()
    assert target.damage_marked == 0
    assert target.counters.get('+1/+1') == 1


def test_divided_damage_copy_keeps_allocations_and_does_not_redistribute_illegal_share():
    engine, original = _bolt()
    first = _creature(engine, 'First')
    second = _creature(engine, 'Second', toughness=10)
    original.effects = build_effects([EffectSpec('damage', {
        'amount': 4, 'target_kind': 'creature', 'count': 2, 'divided': True,
    })], original.obj)
    original.effects[0].division = [1, 3]
    original.targets = [first, second]
    original.target_incarnations = [first.zone_incarnation, second.zone_incarnation]
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    if engine.state.pending_choice:
        engine.rules.resolve_choice('decline')
    assert copied.effects[0].division == [1, 3]
    _blink(engine, first)
    engine.rules.resolve_top_of_stack()
    assert first.damage_marked == 0
    assert second.damage_marked == 3


def test_copy_fight_does_not_shift_second_target_into_illegal_fighter_slot():
    engine, original = _bolt()
    first, second = _creature(engine, 'First'), _creature(engine, 'Second', 'p2')
    original.effects = build_effects([EffectSpec('fight', {
        'fighter_kind': 'creature_you_control', 'other_kind': 'creature_you_dont_control',
    })], original.obj)
    original.targets = [first, second]
    original.target_groups = [[first], [second]]
    original.target_incarnations = [first.zone_incarnation, second.zone_incarnation]
    engine.rules.copy_spell(original, 'p1', choose_new_targets=True)
    if engine.state.pending_choice:
        engine.rules.resolve_choice('decline')
    _blink(engine, first)
    engine.rules.resolve_top_of_stack()
    assert first.damage_marked == second.damage_marked == 0


def _gogo_activation():
    engine, original = _bolt()
    gogo = GameObject(CardDatabase(DB_PATH).get_card('Gogo, Master of Mimicry'),
                      owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(gogo)
    engine.state.add_to_battlefield(gogo)
    gogo.summoning_sick = False
    source = _creature(engine, 'Ability source')
    ability = StackItem(kind='ability', controller_id='p1', source=source,
                        effects=build_effects([EffectSpec('damage', {'amount': 1, 'target_kind': 'player'})], source),
                        targets=original.targets)
    engine.state.stack = [ability]
    player = engine.state.player_by_id('p1')
    player.mana_pool.add('C', 4)
    return engine, player, gogo, ability


def test_gogo_zero_x_is_rejected_before_payment_and_positive_x_is_offered():
    engine, player, gogo, ability = _gogo_activation()
    activated = gogo.activated_abilities[0]
    assert not engine.can_activate(player, gogo, activated, x=0)
    assert engine.can_activate(player, gogo, activated, x=1)
    mana_before = player.mana_pool.total()
    with pytest.raises(ValueError, match='X must be at least 1'):
        engine.activate_ability(player, gogo, 0, x=0, targets=[{'stack_id': ability.stack_id}])
    assert player.mana_pool.total() == mana_before
    assert not gogo.tapped and engine.state.stack == [ability]
    action = next(a for a in engine.legal_actions(player) if a.get('type') == 'activate_ability'
                  and a.get('instance_id') == gogo.instance_id)
    assert action['min_x'] == 1 and action['max_x'] == 2


def test_gogo_cannot_target_opponents_ability_or_have_its_own_ability_copied():
    engine, player, gogo, ability = _gogo_activation()
    ability.controller_id = 'p2'
    with pytest.raises(ValueError, match='illegal targets'):
        engine.activate_ability(player, gogo, 0, x=1, targets=[{'stack_id': ability.stack_id}])
    assert not gogo.tapped
    ability.controller_id = 'p1'
    engine.activate_ability(player, gogo, 0, x=1, targets=[{'stack_id': ability.stack_id}])
    gogo_item = engine.state.stack[-1]
    assert gogo_item.cant_be_copied
    assert engine.rules.copy_ability(gogo_item, 'p2', choose_new_targets=True) is None
    assert engine.state.stack == [ability, gogo_item]
    assert not engine.state.pending_choice


def test_gogo_copy_count_uses_announced_x_even_when_source_x_changes():
    engine, player, gogo, ability = _gogo_activation()
    engine.activate_ability(player, gogo, 0, x=1, targets=[{'stack_id': ability.stack_id}])
    gogo.x_paid = 3
    engine.rules.resolve_top_of_stack()
    assert len(engine.state.pending_stack_copies) == 1
    engine.rules.resolve_choice('decline')
    assert len(engine.state.stack) == 2


def test_dependent_target_round_uses_new_player_target_on_resume_and_resolution():
    engine, original = _bolt()
    p2_bear = _creature(engine, 'P2 Bear', 'p2')
    p3_bear = _creature(engine, 'P3 Bear', 'p3')
    original.effects = build_effects([
        EffectSpec('damage', {'amount': 1, 'target_kind': 'opponent'}),
        EffectSpec('destroy', {'target_kind': 'creature_that_player_controls'}),
    ], original.obj)
    original.targets = [engine.state.player_by_id('p2'), p2_bear]
    original.target_groups = [[original.targets[0]], [p2_bear]]
    original.target_incarnations = [None, p2_bear.zone_incarnation]
    engine.rules.copy_spell(original, 'p1', choose_new_targets=True)
    _choose(engine, 'p3')
    options = engine.state.pending_choice['options']
    assert not any(o.get('instance_id') == p2_bear.instance_id for o in options)
    _choose_object(engine, p3_bear)
    engine.rules.resolve_top_of_stack()
    assert p3_bear.zone == Zone.GRAVEYARD and p2_bear.zone == Zone.BATTLEFIELD
    assert engine.state.player_by_id('p3').life == 19


def test_copy_keeps_announced_x_target_count_and_selected_instructions():
    engine, original = _bolt()
    a, b, c = (_creature(engine, name) for name in ('A', 'B', 'C'))
    original.x = original.obj.x_paid = 2
    original.effects = build_effects([
        EffectSpec('destroy', {'target_kind': 'creature', 'count': 10, 'count_selector': 'source_x_paid'}),
        EffectSpec('damage', {'amount': 'x', 'target_kind': 'player'}),
    ], original.obj)
    original.targets = [a, b, engine.state.player_by_id('p2')]
    original.target_groups = [[a, b], [original.targets[-1]]]
    original.target_incarnations = [a.zone_incarnation, b.zone_incarnation, None]
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    _choose_object(engine, c)
    engine.rules.resolve_choice('decline')
    assert copied.x == copied.obj.x_paid == 2
    assert copied.targets == [c, b, engine.state.player_by_id('p2')]
    engine.rules.resolve_top_of_stack()
    assert c.zone == b.zone == Zone.GRAVEYARD and a.zone == Zone.BATTLEFIELD
    assert engine.state.player_by_id('p2').life == 18


def test_session_rewind_restores_pending_batch_and_routes_choices_to_fresh_engine():
    import json
    from mtg_analyzer.services.game_session import GameSession

    engine, original = _bolt()
    engine.rules.copy_spell(original, 'p1', 2, choose_new_targets=True)
    session = GameSession(engine, mode='replay', require_setup=False)
    choice = session.view()['pending_choice']
    json.dumps(choice)  # The shared board receives IDs, never live copy frames.
    first_pick = next(o['id'] for o in choice['options'] if o.get('player_id') == 'p3')
    session.apply_action({'type': 'choose', 'option_id': first_pick})
    assert len(session.engine.state.ready_stack_copies) == 1
    session.rewind()
    restored = session.engine
    assert restored is not engine
    assert len(restored.state.pending_stack_copies) == 2
    assert not restored.state.ready_stack_copies
    session.apply_action({'type': 'decline'})
    session.apply_action({'type': 'decline'})
    assert restored.state.player_by_id('p2').life == 11
    assert restored.state.player_by_id('p3').life == 20
    assert engine.state.player_by_id('p2').life == 20


def test_per_opponent_copies_can_swap_controllers_without_duplicate_controller_targets():
    engine, original = _bolt()
    p2a, p2b = (_creature(engine, name, 'p2') for name in ('P2 A', 'P2 B'))
    p3a, p3b = (_creature(engine, name, 'p3') for name in ('P3 A', 'P3 B'))
    original.effects = build_effects([EffectSpec('damage', {
        'amount': 1, 'target_kind': 'creature_that_player_controls', 'per_player': 'opponents',
    })], original.obj)
    original.targets = [p2a, p3a]
    original.target_groups = [[p2a, p3a]]
    original.target_incarnations = [p2a.zone_incarnation, p3a.zone_incarnation]
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    _choose_object(engine, p3b)
    choice = engine.state.pending_choice
    assert not any(o.get('instance_id') in (p3a.instance_id, p3b.instance_id) for o in choice['options'])
    assert not choice['optional']
    _choose_object(engine, p2b)
    assert copied.targets == [p3b, p2b]
    engine.rules.resolve_top_of_stack()
    assert p3b.damage_marked == p2b.damage_marked == 1
    assert p3a.damage_marked == p2a.damage_marked == 0


def test_dependent_target_uses_prior_permanents_controller():
    engine, original = _bolt()
    first = _creature(engine, 'First', 'p2')
    second = _creature(engine, 'Second', 'p2')
    replacement = _creature(engine, 'Replacement', 'p3')
    replacement_second = _creature(engine, 'Replacement second', 'p3')
    original.effects = build_effects([
        EffectSpec('damage', {'amount': 1, 'target_kind': 'creature_you_dont_control'}),
        EffectSpec('destroy', {'target_kind': 'creature_that_player_controls'}),
    ], original.obj)
    original.targets = [first, second]
    original.target_groups = [[first], [second]]
    original.target_incarnations = [first.zone_incarnation, second.zone_incarnation]
    engine.rules.copy_spell(original, 'p1', choose_new_targets=True)
    _choose_object(engine, replacement)
    assert not any(o.get('instance_id') == second.instance_id for o in engine.state.pending_choice['options'])
    _choose_object(engine, replacement_second)
    engine.rules.resolve_top_of_stack()
    assert replacement.damage_marked == 1
    assert replacement_second.zone == Zone.GRAVEYARD
    assert first.damage_marked == 0 and second.zone == Zone.BATTLEFIELD


def _permanent_spell(engine, name, target, *, bestow=False, mutate=False):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id='p1', zone=Zone.STACK)
    bind_from_catalogue(obj)
    if bestow:
        engine.rules._begin_bestow(obj)
    obj.cast_via_mutate = mutate
    item = StackItem(kind='spell', controller_id='p1', obj=obj, effects=[], targets=[target])
    engine.state.stack = [item]
    return item


def test_aura_copy_offers_its_enchant_target_and_attaches_to_new_choice():
    engine, _ = _bolt()
    first, second = _creature(engine, 'First'), _creature(engine, 'Second')
    original = _permanent_spell(engine, 'Rancor', first)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    _choose_object(engine, second)
    engine.rules.resolve_top_of_stack()
    assert copied.obj in engine.state.battlefield
    assert copied.obj.attached_to == second.instance_id
    assert original.targets == [first]


def test_aura_copy_with_stale_kept_target_never_enters_battlefield():
    from mtg_analyzer.models.game.events import EventType

    engine, _ = _bolt()
    first, _ = _creature(engine, 'First'), _creature(engine, 'Other')
    original = _permanent_spell(engine, 'Rancor', first)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    engine.rules.resolve_choice('decline')
    _blink(engine, first)
    engine.rules.resolve_top_of_stack()
    assert copied.obj not in engine.state.battlefield
    assert not any(e.type == EventType.ENTERS_BATTLEFIELD and e.get('instance_id') == copied.obj.instance_id
                   for e in engine.state.event_log)


@pytest.mark.parametrize('name,bestow,mutate', [
    ('Boon Satyr', True, False), ('Gemrazer', False, True),
])
def test_bestow_and_mutate_copies_with_stale_targets_resolve_as_creatures(name, bestow, mutate):
    engine, _ = _bolt()
    first, _ = _creature(engine, 'First'), _creature(engine, 'Other')
    original = _permanent_spell(engine, name, first, bestow=bestow, mutate=mutate)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    engine.rules.resolve_choice('decline')
    _blink(engine, first)
    engine.rules.resolve_top_of_stack()
    assert copied.obj in engine.state.battlefield and copied.obj.is_creature
    assert not copied.obj.attached_to and not copied.obj.bestowed
    assert not first.merged_oracle_text


@pytest.mark.parametrize('name,bestow,mutate', [
    ('Boon Satyr', True, False), ('Gemrazer', False, True),
])
def test_bestow_and_mutate_copy_keep_alternative_cost_choice_when_retargeted(name, bestow, mutate):
    engine, _ = _bolt()
    first, second = _creature(engine, 'First'), _creature(engine, 'Second')
    original = _permanent_spell(engine, name, first, bestow=bestow, mutate=mutate)
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    _choose_object(engine, second)
    engine.rules.resolve_top_of_stack()
    if bestow:
        assert copied.obj.bestowed and not copied.obj.is_creature
        assert copied.obj.attached_to == second.instance_id
    else:
        assert second.name == name
        assert copied.obj not in engine.state.battlefield
    assert first.name == 'First'


def _counter_copy_fixture(*, extra_spell=None):
    engine, original = _bolt()
    other_obj = GameObject(CardDatabase(DB_PATH).get_card('Lightning Bolt'), owner_id='p2', zone=Zone.STACK)
    bind_from_catalogue(other_obj)
    other = StackItem(kind='spell', controller_id='p2', obj=other_obj,
                      effects=other_obj.spell_effects, targets=[engine.state.player_by_id('p1')])
    original.effects = build_effects([EffectSpec('counter', {'target_kind': 'spell'})], original.obj)
    original.targets = [other]
    original.target_incarnations = [other.obj.zone_incarnation]
    engine.state.stack = ([StackItem(kind='spell', controller_id='p2', obj=extra_spell)]
                          if extra_spell is not None else []) + [other, original]
    copied = engine.rules.copy_spell(original, 'p1', choose_new_targets=True)[0]
    return engine, original, other, copied


def test_stack_item_and_spell_object_identify_the_same_retained_target():
    engine, original, other, copied = _counter_copy_fixture()
    options = engine.state.pending_choice['options']
    assert not any(o.get('instance_id') == other.obj.instance_id for o in options)
    engine.rules.resolve_choice('decline')
    engine.rules.resolve_top_of_stack()
    assert other not in engine.state.stack and original in engine.state.stack


def test_retained_stack_item_does_not_counter_a_later_casting_of_the_same_card():
    engine, original, other, copied = _counter_copy_fixture()
    engine.rules.resolve_choice('decline')
    engine.state.stack.remove(other)
    other.obj.zone = Zone.GRAVEYARD
    other.obj.zone = Zone.STACK
    recast = StackItem(kind='spell', controller_id='p2', obj=other.obj, effects=other.effects,
                       targets=other.targets)
    engine.state.stack.insert(0, recast)
    engine.rules.resolve_top_of_stack()
    assert recast in engine.state.stack
    assert copied not in engine.state.stack


def test_new_spell_target_with_ward_does_not_trigger_battlefield_ward():
    warded = GameObject(Card(id='wardspell', name='Warded Spell', type_line='Creature — Bear',
                             is_creature=True, power=2, toughness=2), owner_id='p2', zone=Zone.STACK)
    warded.parametric_keywords = {'ward': {'cost': '{2}'}}
    engine, original, other, copied = _counter_copy_fixture(extra_spell=warded)
    warded_item = engine.state.stack[0]
    _choose_object(engine, warded)
    assert engine.state.stack == [warded_item, other, original, copied]


def test_copy_of_cast_modal_spell_keeps_chosen_mode_and_retargets_its_damage():
    engine, _ = _bolt()
    engine.state.stack = []
    first = _creature(engine, 'First', toughness=4)
    second = _creature(engine, 'Second', toughness=4)
    spell = GameObject(CardDatabase(DB_PATH).get_card('Izzet Charm'), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player = engine.state.player_by_id('p1')
    player.hand.append(spell)
    player.mana_pool.add_many({'U': 1, 'R': 1})
    engine.cast_spell(player, spell, mode=1, targets=[first])
    original = engine.state.stack[-1]
    copied = engine.rules.copy_spell(original, 'p2', choose_new_targets=True)[0]
    _choose_object(engine, second)
    engine.rules.resolve_top_of_stack()
    assert first.damage_marked == 0 and second.damage_marked == 2
    assert not engine.state.pending_choice
    assert original in engine.state.stack and copied not in engine.state.stack
