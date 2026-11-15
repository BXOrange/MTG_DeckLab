"""The Cosplayzer copies only the first ability occurrence per creature and turn."""
from mtg_analyzer.game.effects.counters_tokens import EnterAsCopyReplacement
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.deck_batch import card, cast, game, filler, put_on_battlefield
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.card_catalogue.t.the_cosplayzer import COPY_LINE


def cosplay(engine, target):
    source = card(engine, 'The Cosplayzer', zone=Zone.HAND)
    cast(engine, source)
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_until_stable()
    return source


def settle(engine):
    for _ in range(20):
        engine.resolve_until_stable()
        choice = engine.state.pending_choice
        if choice is None:
            return
        assert choice['kind'] in ('order_triggers', 'copy_targets', 'copied_mana_option'), choice
        answer = 'keep' if choice['kind'] == 'copy_targets' else str(choice['options'][0]['id'])
        engine.resolve_pending_choice(answer)
    raise AssertionError('ability-copy resolution did not finish')


def entering_copy(engine, target, answer=None):
    source = card(engine, 'Clone', zone=Zone.HAND)
    source.enter_as_copy_effects = [EnterAsCopyReplacement(
        target_kind='creature', name_first_letter='Z',
    )]
    cast(engine, source)
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice(answer or str(target.instance_id))
    engine.resolve_until_stable()
    return source


def test_entry_replaces_first_letter_and_leaves_original_unchanged():
    engine = game(); target = card(engine, 'Grizzly Bears', player='p2')
    source = entering_copy(engine, target)
    assert source.name == 'Zrizzly Bears' and source.power == 2
    assert target.name == 'Grizzly Bears'


def test_declining_copy_does_not_rename_and_zero_toughness_dies():
    engine = game(); target = card(engine, 'Grizzly Bears')
    source = entering_copy(engine, target, 'decline')
    assert source.name == 'Clone' and source.zone == Zone.GRAVEYARD


def test_further_copy_keeps_renamed_name_and_authored_abilities():
    engine = game(); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = entering_copy(engine, target)
    token = engine.rules.copy_permanent(controller_id='p1', source=source, not_legendary=True)[0]
    assert token.name == 'Zurie, Emergent Intelligence'
    assert len(token.activated_abilities) == len(target.activated_abilities) == 1
    assert len(token.triggered_abilities) == len(target.triggered_abilities) == 1
    player = engine.state.players[0]
    before = len(player.hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=token, combat=True)
    engine.resolve_until_stable()
    assert len(player.hand) == before + 1


def test_serialized_renamed_copy_rebinds_original_authored_abilities():
    engine = game(); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = entering_copy(engine, target)
    restored = GameObject(Card.from_dict(source.card.to_dict()), owner_id='p1')
    bind_from_catalogue(restored)
    assert restored.name == 'Zurie, Emergent Intelligence'
    assert len(restored.activated_abilities) == len(source.activated_abilities) == 1
    assert len(restored.triggered_abilities) == len(source.triggered_abilities) == 1


def test_further_copy_retains_usable_mana_ability():
    engine = game(); target = card(engine, 'Llanowar Elves', player='p2')
    source = entering_copy(engine, target)
    token = engine.rules.copy_permanent(controller_id='p1', source=source)[0]
    token.summoning_sick = False
    player = engine.state.players[0]
    player.mana_pool.empty()
    engine.tap_for_mana(player, token)
    assert token.name == 'Zlanowar Elves' and player.mana_pool.total() == 1


def test_real_cosplayzer_copies_first_trigger_without_recursion():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target)
    before = len(engine.state.players[0].hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    settle(engine)
    assert len(engine.state.players[0].hand) == before + 2
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    settle(engine)
    assert len(engine.state.players[0].hand) == before + 3


def test_real_cosplayzer_copies_first_activation_only():
    engine = game(library=30); target = card(engine, 'Prodigal Sorcerer', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    opponent = engine.state.players[1]
    before = opponent.life
    engine.activate_ability(engine.state.players[0], source, 0, targets=[opponent])
    settle(engine)
    assert opponent.life == before - 2
    source.tapped = False
    engine.activate_ability(engine.state.players[0], source, 0, targets=[opponent])
    settle(engine)
    assert opponent.life == before - 3


def place_triggers(engine):
    engine.rules.put_triggers_on_stack()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        assert choice['kind'] == 'order_triggers'
        engine.resolve_pending_choice(str(choice['options'][0]['id']))


def test_trigger_copy_survives_original_being_countered():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target); before = len(engine.state.players[0].hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    place_triggers(engine)
    original = next(item for item in engine.state.stack if item.description != COPY_LINE)
    engine.rules.counter_ability(original)
    settle(engine)
    assert len(engine.state.players[0].hand) == before + 1


def test_pending_trigger_receipt_survives_clone_before_placement():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target); before = len(engine.state.players[0].hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    restored = GameEngine(engine.state.clone())
    settle(restored)
    assert len(restored.state.players[0].hand) == before + 2
    assert len(engine.state.players[0].hand) == before


def test_trigger_and_activation_share_one_first_occurrence():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    settle(engine)
    food = card(engine, 'Ornithopter')
    engine.state.players[0].mana_pool.add_many({'C': 1, 'U': 1})
    engine.activate_ability(engine.state.players[0], source, 0, tap_choices=[food.instance_id])
    assert not engine.rules.pending_triggers
    assert len(engine.state.stack) == 1
    settle(engine)
    assert source.name == 'Ornithopter'


def test_first_mana_activation_is_copied_without_tapping_or_paying_again():
    engine = game(); target = card(engine, 'Llanowar Elves', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, source)
    assert player.mana_pool.total() == 1
    settle(engine)
    assert player.mana_pool.total() == 2 and source.tapped
    source.tapped = False
    engine.tap_for_mana(player, source); settle(engine)
    assert player.mana_pool.total() == 3


def test_copied_mana_ability_repeats_its_damage_rider():
    engine = game(); target = card(engine, 'Elves of Deep Shadow', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty(); before = player.life
    engine.tap_for_mana(player, source); settle(engine)
    assert player.mana_pool.total() == 2 and player.life == before - 2


def test_mana_activation_consumes_shared_first_use_before_later_trigger():
    engine = game(library=30); target = card(engine, 'Marwyn, the Nurturer', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    engine.state.players[0].mana_pool.empty()
    engine.tap_for_mana(engine.state.players[0], source); settle(engine)
    assert engine.state.players[0].mana_pool.total() == 2
    put_on_battlefield(engine, 'Llanowar Elves'); settle(engine)
    assert source.counters.get('+1/+1', 0) == 1


def test_copied_variable_mana_remeasures_at_resolution_and_does_not_repay_cost():
    engine = game(); target = card(engine, 'Selvala, Heart of the Wilds', player='p2')
    card(engine, 'Colossal Dreadmaw')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty(); player.mana_pool.add('G', 1)
    engine.tap_for_mana(player, source)
    assert player.mana_pool.total() == 6
    filler(engine, 'Larger creature', power=9, toughness=9)
    settle(engine)
    assert player.mana_pool.total() == 15


def test_interactive_trigger_order_and_receipts_survive_undo_snapshot():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target); before = len(engine.state.players[0].hand)
    engine.state.interactive_ordering = True
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True)
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice['kind'] == 'order_triggers'
    restored = GameEngine(engine.state.clone()); settle(restored)
    assert len(restored.state.players[0].hand) == before + 2


def test_copy_can_choose_a_different_damage_target():
    engine = game(players=3); target = card(engine, 'Prodigal Sorcerer', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    p2, p3 = engine.state.players[1:]
    engine.activate_ability(engine.state.players[0], source, 0, targets=[p2])
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice['kind'] == 'copy_targets'
    option = next(option for option in choice['options'] if option.get('player_id') == p3.id)
    engine.resolve_pending_choice(option['id']); settle(engine)
    assert p2.life == p3.life == 19


def test_copied_mana_can_choose_a_new_color():
    engine = game(); target = card(engine, 'Birds of Paradise', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, source, option_index=0)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice['kind'] == 'copied_mana_option'
    engine.resolve_pending_choice('1'); settle(engine)
    assert player.mana_pool.to_dict()['W'] == 1 and player.mana_pool.to_dict()['U'] == 1


def test_first_use_resets_on_opponents_turn():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target); player = engine.state.players[0]
    before = len(player.hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True); settle(engine)
    engine.state.internal_turn.number += 1
    engine.state.active_player_index = 1
    engine.rules.deal_damage(engine.state.players[1], 1, source=source, combat=True); settle(engine)
    assert len(player.hand) == before + 4


def test_serialized_copy_keeps_intrinsic_copy_trigger_and_renamed_name():
    engine = game(library=30); target = card(engine, 'Curie, Emergent Intelligence', player='p2')
    source = cosplay(engine, target)
    saved = source.card.to_dict(); engine.rules.exile(source)
    restored = GameObject(Card.from_dict(saved), owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(restored); engine.state.add_to_battlefield(restored)
    engine.recompute_continuous_effects()
    assert restored.name == 'Zurie, Emergent Intelligence'
    before = len(engine.state.players[0].hand)
    engine.rules.deal_damage(engine.state.players[1], 1, source=restored, combat=True); settle(engine)
    assert len(engine.state.players[0].hand) == before + 2


def test_ward_trigger_is_copied_as_first_ability():
    engine = game(); target = card(engine, 'Colossal Skyturtle', player='p2')
    source = cosplay(engine, target)
    pinger = card(engine, 'Prodigal Sorcerer', player='p2')
    engine.state.players[1].mana_pool.empty()
    engine.activate_ability(engine.state.players[1], pinger, 0, targets=[source])
    assert any(event.type == 'ABILITY_TRIGGERED' and event.get('instance_id') == source.instance_id
               for event in engine.state.events_this_turn())
    assert any(ability.description == COPY_LINE for ability, event in engine.rules.pending_triggers)
    settle(engine)
    assert source.damage_marked == 0


def test_name_exception_skips_leading_digits():
    engine = game(); target = filler(engine, '1996 World Champion', power=2, toughness=2)
    source = cosplay(engine, target)
    assert source.name == '1996 Zorld Champion'


def test_copying_a_cosplayzer_keeps_both_intrinsic_copy_abilities():
    engine = game(); target = card(engine, 'Prodigal Sorcerer', player='p2')
    first = cosplay(engine, target)
    second = cosplay(engine, first); second.summoning_sick = False
    opponent = engine.state.players[1]
    assert second.card.granted_ability_lines == (COPY_LINE, COPY_LINE)
    engine.activate_ability(engine.state.players[0], second, 0, targets=[opponent]); settle(engine)
    assert opponent.life == 17


def test_actual_entry_can_be_declined():
    engine = game(); card(engine, 'Grizzly Bears')
    source = card(engine, 'The Cosplayzer', zone=Zone.HAND)
    cast(engine, source); engine.resolve_pending_choice('decline'); settle(engine)
    assert source.name == 'The Cosplayzer' and source.zone == Zone.GRAVEYARD


def test_registered_entry_specs_are_fresh_and_bind():
    from mtg_analyzer.game.card_registry.core import specs_for

    engine = game(); source = card(engine, 'The Cosplayzer', zone=Zone.HAND)
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert len(source.enter_as_copy_effects) == 1


def test_mana_copy_does_not_repeat_tap_only_production_replacement():
    engine = game(); target = card(engine, 'Llanowar Elves', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    card(engine, 'Nyxbloom Ancient')
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, source); settle(engine)
    assert player.mana_pool.total() == 4
    taps = [event for event in engine.state.events_this_turn()
            if event.type == 'TAPPED_FOR_MANA' and event.get('instance_id') == source.instance_id]
    assert len(taps) == 1


def test_combination_choice_keeps_distribution_across_clone():
    engine = game(); target = card(engine, 'Selvala, Heart of the Wilds', player='p2')
    card(engine, 'Colossal Dreadmaw')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty(); player.mana_pool.add('G', 1)
    engine.tap_for_mana(player, source); engine.resolve_until_stable()
    assert engine.state.pending_choice['kind'] == 'copied_mana_option'
    engine.resolve_pending_choice('1')
    restored = GameEngine(engine.state.clone())
    restored.resolve_pending_choice('1'); settle(restored)
    mana = restored.state.players[0].mana_pool.to_dict()
    assert mana['W'] == 10 and mana['U'] == 2


def test_triggered_mana_ability_is_also_copied():
    engine = game(); target = card(engine, 'Kinnan, Bonder Prodigy', player='p2')
    cosplay(engine, target)
    elf = card(engine, 'Llanowar Elves')
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, elf)
    assert player.mana_pool.total() == 2
    settle(engine)
    assert player.mana_pool.total() == 3


def test_mana_copy_survives_source_departure():
    engine = game(); target = card(engine, 'Llanowar Elves', player='p2')
    source = cosplay(engine, target); source.summoning_sick = False
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, source)
    engine.rules.exile(source); settle(engine)
    assert player.mana_pool.total() == 2 and source.zone == Zone.EXILE


def test_trigger_recipe_gets_targets_announced_after_firing_and_clone():
    engine = game(); template = card(engine, 'Flametongue Kavu', player='p2')
    victim = card(engine, 'Colossal Dreadmaw', player='p2')
    source = cosplay(engine, template)
    assert engine.state.pending_choice['kind'] == 'trigger_target'
    restored = GameEngine(engine.state.clone())
    restored.resolve_pending_choice(str(victim.instance_id)); settle(restored)
    assert restored.state.find_object(victim.instance_id).zone == Zone.GRAVEYARD
    assert restored.state.find_object(source.instance_id).zone == Zone.BATTLEFIELD
    assert victim.zone == Zone.BATTLEFIELD
