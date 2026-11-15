"""Vesuvan Drifter reveals at resolution and copies only a revealed creature until cleanup."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.top_library import may_look_at_top_of_library
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game, step


def board(top='Grizzly Bears'):
    engine = game(players=3, library=30)
    source = card(engine, 'Vesuvan Drifter')
    revealed = card(engine, top, zone=Zone.LIBRARY) if top else None
    return engine, source, revealed


def announce(engine, player='p1'):
    step(engine, 'begin_combat', player)
    assert engine.state.pending_choice['kind'] == 'composite_optional'


def accept(engine):
    engine.resolve_pending_choice('yes'); engine.resolve_until_stable()


def reveals(engine):
    return [event for event in engine.state.events_this_turn() if event.type == 'REVEAL']


def test_fresh_specs_bind_flying_look_and_trigger():
    engine, source, top = board()
    a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[1].effects[0] is not b[1].effects[0]
    assert combat.has(source, 'flying') and len(source.triggered_abilities) == 1
    assert may_look_at_top_of_library(engine.state.players[0], engine.state)
    assert not may_look_at_top_of_library(engine.state.players[1], engine.state)


def test_real_cast_binds_permission_and_combat_trigger():
    engine = game(library=30)
    source = card(engine, 'Vesuvan Drifter', zone=Zone.HAND); cast(engine, source)
    assert source in engine.state.battlefield and combat.has(source, 'flying')
    assert may_look_at_top_of_library(engine.state.players[0], engine.state)
    announce(engine)


def test_accepting_reveals_and_copies_creature_with_intrinsic_flying():
    engine, source, top = board(); announce(engine); accept(engine)
    assert source.name == 'Grizzly Bears' and source.power == 2 and source.toughness == 2
    assert combat.has(source, 'flying') and 'Flying' in source.card.keywords
    assert top.zone == Zone.LIBRARY and engine.state.players[0].library[-1] is top
    assert reveals(engine)[-1].get('instance_id') == top.instance_id


def test_declining_reveals_nothing_and_keeps_original():
    engine, source, top = board(); announce(engine)
    engine.resolve_pending_choice('decline'); engine.resolve_until_stable()
    assert source.name == 'Vesuvan Drifter' and not reveals(engine)


def test_noncreature_is_revealed_but_not_copied():
    engine, source, top = board('Sol Ring'); announce(engine); accept(engine)
    assert source.name == 'Vesuvan Drifter' and reveals(engine)[-1].get('instance_id') == top.instance_id


def test_empty_library_reveals_nothing_and_does_not_copy_old_referent():
    engine, source, top = board()
    engine.state.players[0].library.clear()
    engine.rules.context.revealed_card = top
    announce(engine); accept(engine)
    assert source.name == 'Vesuvan Drifter' and not reveals(engine)


def test_opponents_combat_also_triggers_for_controllers_library():
    engine, source, top = board(); announce(engine, 'p2'); accept(engine)
    assert source.name == top.name and reveals(engine)[-1].get('player_id') == 'p1'


def test_top_card_is_chosen_at_resolution():
    engine, source, top = board(); announce(engine)
    replacement = card(engine, 'Llanowar Elves', zone=Zone.LIBRARY)
    accept(engine)
    assert source.name == replacement.name and reveals(engine)[-1].get('instance_id') == replacement.instance_id


def test_copy_loses_original_look_and_combat_ability_until_cleanup():
    engine, source, top = board(); announce(engine); accept(engine)
    assert not source.triggered_abilities
    assert not may_look_at_top_of_library(engine.state.players[0], engine.state)
    engine._step_cleanup(); engine.recompute_continuous_effects()
    assert source.name == 'Vesuvan Drifter' and len(source.triggered_abilities) == 1
    assert may_look_at_top_of_library(engine.state.players[0], engine.state)


def test_copy_does_not_enter_again_or_trigger_copied_etb():
    engine, source, top = board('Elvish Visionary')
    before = len(engine.state.players[0].hand)
    announce(engine); accept(engine)
    assert source.name == top.name and len(engine.state.players[0].hand) == before
    assert len(source.triggered_abilities) == 1


def test_copied_mana_ability_is_usable():
    engine, source, top = board('Llanowar Elves'); announce(engine); accept(engine)
    player = engine.state.players[0]; player.mana_pool.empty()
    engine.tap_for_mana(player, source)
    assert player.mana_pool.to_dict()['G'] == 1


def test_copy_keeps_counters_and_tapped_state():
    engine, source, top = board(); source.add_counters('+1/+1', 2); source.tapped = True
    announce(engine); accept(engine)
    assert source.tapped and source.power == 4 and source.counters['+1/+1'] == 2


def test_other_copy_inherits_flying_but_not_originals_expiration():
    engine, source, top = board(); announce(engine); accept(engine)
    token = engine.rules.copy_permanent(controller_id='p1', source=source)[0]
    engine._step_cleanup(); engine.recompute_continuous_effects()
    assert source.name == 'Vesuvan Drifter' and token.name == 'Grizzly Bears'
    assert combat.has(token, 'flying')


def test_departed_source_still_reveals_but_cannot_become_a_copy():
    engine, source, top = board(); announce(engine)
    engine.rules.put_into_graveyard(source); accept(engine)
    assert source.zone == Zone.GRAVEYARD and source.name == 'Vesuvan Drifter'
    assert reveals(engine)[-1].get('instance_id') == top.instance_id


def test_old_trigger_does_not_change_returned_source():
    engine, source, top = board(); announce(engine)
    engine.rules.put_into_graveyard(source); engine.rules.return_from_graveyard(source, 'battlefield')
    accept(engine)
    assert source.name == 'Vesuvan Drifter' and source.zone == Zone.BATTLEFIELD
    assert reveals(engine)[-1].get('instance_id') == top.instance_id


def test_optional_resolution_survives_clone():
    engine, source, top = board(); announce(engine)
    restored = GameEngine(engine.state.clone()); accept(restored)
    assert restored.state.find_object(source.instance_id).name == 'Grizzly Bears'
    assert source.name == 'Vesuvan Drifter'


def test_control_change_after_trigger_keeps_original_controllers_library():
    engine, source, top = board()
    card(engine, 'Llanowar Elves', player='p2', zone=Zone.LIBRARY)
    announce(engine); source.controller_id = 'p2'
    engine.recompute_continuous_effects(); accept(engine)
    assert source.name == top.name and source.controller_id == 'p2'
    assert reveals(engine)[-1].get('player_id') == 'p1'


def test_noncreature_reveal_allows_another_trigger_in_additional_combat():
    engine, source, top = board('Sol Ring'); announce(engine); accept(engine)
    creature = card(engine, 'Grizzly Bears', zone=Zone.LIBRARY)
    announce(engine); accept(engine)
    assert source.name == creature.name and len(reveals(engine)) == 2


def test_countered_trigger_never_reveals_or_offers_optional_copy():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, source, top = board()
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='begin_combat', player_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_ability(engine.state.stack[-1]); engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not reveals(engine)
    assert source.name == 'Vesuvan Drifter'
