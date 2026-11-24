"""Firion copies nontoken Equipment, discounts only the copy's equip and sacrifices it next upkeep."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_catalogue.f.firion_wild_rose_warrior import DISCOUNT_LINE
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, enter, filler, game, named, step
from tests.support.star_trek import advance_to


def board():
    engine = game(players=3, library=40)
    advance_to(engine, 'main1')
    source = card(engine, 'Firion, Wild Rose Warrior')
    return engine, source, engine.state.players[0]


def equipment(engine, name='Loxodon Warhammer', player='p1'):
    original = card(engine, name, player=player)
    enter(engine, original)
    return original


def token_for(engine, name='Loxodon Warhammer'):
    return next(o for o in named(engine, name) if o.is_token)


def equip_ability(obj):
    return next((i, a) for i, a in enumerate(obj.activated_abilities) if a.cost.attach_kind == 'equip')


def equip_cost(engine, obj):
    index, ability = equip_ability(obj)
    return engine._reduced_activation_mana(obj, ability.cost.mana, cost=ability.cost)


def test_specs_fresh_and_both_abilities_bind():
    engine, source, player = board(); a, b = specs_for(source.card), specs_for(source.card)
    assert len(a) == 2 and a[1] is not b[1] and a[1].effects[0] is not b[1].effects[0]
    assert source.static_effects and len(source.triggered_abilities) == 1


def test_own_nontoken_equipment_entry_creates_one_token_without_looping():
    engine, source, player = board(); original = equipment(engine); token = token_for(engine)
    assert len(named(engine, original.name)) == 2
    assert token.card.granted_ability_lines == (DISCOUNT_LINE,)
    assert len(engine.state.delayed_triggers) == 1
    assert not engine.state.pending_choice


def test_other_players_equipment_entry_does_not_trigger():
    engine, source, player = board(); equipment(engine, player='p2')
    assert not named(engine, 'Loxodon Warhammer') and not engine.state.delayed_triggers


def test_token_equipment_entry_does_not_trigger():
    engine, source, player = board()
    original = card(engine, 'Loxodon Warhammer'); original.is_token = True
    enter(engine, original)
    assert named(engine, original.name) == [original] and not engine.state.delayed_triggers


def test_nonequipment_artifact_entry_does_not_trigger():
    engine, source, player = board(); original = card(engine, 'Sol Ring'); enter(engine, original)
    assert named(engine, 'Sol Ring') == [original]


def test_discount_applies_only_to_created_token_equips():
    engine, source, player = board(); original = equipment(engine); token = token_for(engine)
    assert equip_cost(engine, original).resolved_value == 3
    assert equip_cost(engine, token).resolved_value == 1


def test_reduced_equip_cost_is_paid_and_attachment_grants_haste():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    creature = card(engine, 'Grizzly Bears'); creature.summoning_sick = True
    player.mana_pool.add('C', 1)
    index, ability = equip_ability(token)
    engine.activate_ability(player, token, index, targets=[creature]); engine.resolve_until_stable()
    assert token.attached_to == creature.instance_id and player.mana_pool.total() == 0
    assert combat.has(creature, 'haste')


def test_equip_discount_floors_generic_cost_at_zero():
    engine, source, player = board(); equipment(engine, 'Bonesplitter')
    assert equip_cost(engine, token_for(engine, 'Bonesplitter')).resolved_value == 0


def test_equip_discount_preserves_colored_mana_and_other_activation_costs():
    engine, source, player = board()
    original = filler(engine, 'Test Equipment', type_line='Artifact — Equipment',
        oracle_text='{3}: Draw a card.\nEquip {1}{W}', keywords=['Equip'])
    enter(engine, original); token = token_for(engine, original.name)
    assert equip_cost(engine, token).render() == '{W}'
    other = next(a for a in token.activated_abilities if a.cost.attach_kind != 'equip')
    assert engine._reduced_activation_mana(token, other.cost.mana, cost=other.cost).resolved_value == 3


def test_first_any_players_upkeep_sacrifices_token_not_original():
    engine, source, player = board(); original = equipment(engine); token = token_for(engine)
    step(engine, 'upkeep', player='p2')
    assert token not in engine.state.battlefield and original in engine.state.battlefield
    assert not engine.state.delayed_triggers


def test_delayed_sacrifice_survives_firion_leaving():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    engine.rules.exile(source); step(engine, 'upkeep', player='p2')
    assert token not in engine.state.battlefield


def test_countering_entry_trigger_prevents_copy():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer')
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=original.instance_id,
        controller_id=player.id, object=original.name, object_types=sorted(original.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.counter_spell(engine.state.stack[-1])
    engine.resolve_until_stable()
    assert named(engine, original.name) == [original] and not engine.state.delayed_triggers


def test_countering_delayed_trigger_does_not_schedule_another_sacrifice():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    engine._fire_delayed_triggers('upkeep'); assert engine.state.stack
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    step(engine, 'upkeep', player='p2')
    assert token in engine.state.battlefield and not engine.state.delayed_triggers


def test_stolen_token_cannot_be_sacrificed_by_original_controller():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    token.controller_id = 'p2'
    step(engine, 'upkeep', player='p2')
    assert token in engine.state.battlefield and not engine.state.delayed_triggers


def test_equip_discount_follows_token_to_new_controller():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    token.controller_id = 'p2'; engine.recompute_continuous_effects()
    assert equip_cost(engine, token).resolved_value == 1


def test_further_token_copy_inherits_discount_but_not_delayed_sacrifice():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    copy = engine.rules.copy_permanent(player.id, token)[0]
    assert copy.card.granted_ability_lines == (DISCOUNT_LINE,)
    assert equip_cost(engine, copy).resolved_value == 1
    step(engine, 'upkeep', player='p2')
    assert token not in engine.state.battlefield and copy in engine.state.battlefield


def test_original_leaving_before_trigger_resolves_uses_last_known_copy_values():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer')
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=original.instance_id,
        controller_id=player.id, object=original.name, object_types=sorted(original.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(original)
    engine.resolve_until_stable()
    assert token_for(engine).name == 'Loxodon Warhammer'


def test_equipped_creatures_only_get_haste_while_firion_is_present():
    engine, source, player = board(); original = equipment(engine)
    own = card(engine, 'Grizzly Bears'); other = card(engine, 'Grizzly Bears', player='p2')
    assert not combat.has(own, 'haste')
    engine.rules.attach_to_target(original, own); engine.recompute_continuous_effects()
    assert combat.has(own, 'haste') and not combat.has(other, 'haste')
    engine.rules.exile(source); engine.recompute_continuous_effects()
    assert not combat.has(own, 'haste')


def test_haste_follows_equipment_moving_to_another_creature():
    engine, source, player = board(); original = equipment(engine)
    first = card(engine, 'Grizzly Bears'); second = card(engine, 'Llanowar Elves')
    engine.rules.attach_to_target(original, first); engine.recompute_continuous_effects()
    assert combat.has(first, 'haste') and not combat.has(second, 'haste')
    engine.rules.attach_to_target(original, second); engine.recompute_continuous_effects()
    assert not combat.has(first, 'haste') and combat.has(second, 'haste')


def test_undo_clone_preserves_copy_discount_and_delayed_sacrifice():
    engine, source, player = board(); equipment(engine); token = token_for(engine)
    clone = GameEngine(engine.state.clone())
    clone_token = clone.state.find_object(token.instance_id)
    assert equip_cost(clone, clone_token).resolved_value == 1
    step(clone, 'upkeep', player='p2')
    assert clone_token not in clone.state.battlefield and token in engine.state.battlefield


def test_real_equipment_cast_triggers_copy_after_resolution():
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer', zone=Zone.HAND)
    cast(engine, original)
    assert token_for(engine).name == original.name


def fire_entry(engine, original):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=original.instance_id,
        controller_id=original.controller_id, object=original.name, object_types=sorted(original.type_words)))
    engine.rules.put_triggers_on_stack()


def test_copy_uses_changed_copiable_values_if_original_is_still_on_battlefield():
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer')
    replacement = card(engine, 'Bonesplitter')
    fire_entry(engine, original)
    engine.rules.become_copy(original, replacement); engine.resolve_until_stable()
    token = token_for(engine, 'Bonesplitter')
    assert equip_cost(engine, token).resolved_value == 0


def test_last_known_equipment_form_is_used_when_copy_effect_ends_on_exile():
    engine, source, player = board(); original = card(engine, 'Sculpting Steel')
    template = card(engine, 'Loxodon Warhammer')
    engine.rules.become_copy(original, template); engine.recompute_continuous_effects()
    fire_entry(engine, original)
    engine.rules.exile(original); engine.resolve_until_stable()
    assert original.name == 'Sculpting Steel' and original.zone == Zone.EXILE
    assert token_for(engine).name == 'Loxodon Warhammer'


def test_entry_trigger_survives_firion_leaving_before_resolution():
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer')
    fire_entry(engine, original); engine.rules.exile(source); engine.resolve_until_stable()
    assert token_for(engine).card.granted_ability_lines == (DISCOUNT_LINE,)


def test_token_doubling_preserves_discount_on_each_copy_and_captures_all_for_upkeep():
    engine, source, player = board(); card(engine, 'Doubling Season')
    equipment(engine)
    tokens = [o for o in named(engine, 'Loxodon Warhammer') if o.is_token]
    assert len(tokens) == 2 and all(equip_cost(engine, o).resolved_value == 1 for o in tokens)
    step(engine, 'upkeep', player='p2')
    assert all(o not in engine.state.battlefield for o in tokens)


def test_unattached_copy_does_not_inherit_original_attachment():
    engine, source, player = board(); original = card(engine, 'Loxodon Warhammer')
    creature = card(engine, 'Grizzly Bears')
    engine.rules.attach_to_target(original, creature)
    enter(engine, original)
    assert original.attached_to == creature.instance_id and token_for(engine).attached_to is None


def test_equipment_back_face_is_copied_as_equipment_not_its_creature_front():
    from mtg_analyzer.game.effects.core import StaticAbility
    engine, source, player = board()
    source.static_effects.append(StaticAbility('ignore_legend_rule', affects='you', params={}, source=source))
    original = card(engine, 'Halvar, God of Battle // Sword of the Realms', zone=Zone.HAND)
    cast(engine, original, face='back')
    token = token_for(engine, 'Sword of the Realms')
    assert token.is_artifact and not token.is_creature
    assert equip_cost(engine, token).render() == '{W}'
