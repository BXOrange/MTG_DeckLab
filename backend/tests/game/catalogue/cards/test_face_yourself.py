"""Face Yourself makes simultaneous token copies with intrinsic conditional end-step triggers."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_catalogue.f.face_yourself import SACRIFICE_LINE
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game, named, step


def board():
    engine = game(players=3, library=40)
    spell = card(engine, 'Face Yourself', zone=Zone.HAND)
    return engine, spell


def create(engine, spell, player='p2'):
    cast(engine, spell, targets=[engine.state.player_by_id(player)])
    return [o for o in engine.state.battlefield if o.is_token and o.controller_id == 'p1']


def planeswalker(engine, player='p1'):
    return filler(engine, 'Planeswalker', type_line='Planeswalker — Test', loyalty=4, player=player)


def test_fresh_spec_and_player_target():
    engine, spell = board(); a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert spell.spell_effects[0].target_spec.kind == 'player'


def test_copies_only_target_players_creatures_under_casters_control():
    engine, spell = board()
    a = card(engine, 'Grizzly Bears', player='p2'); b = card(engine, 'Ornithopter', player='p2')
    card(engine, 'Sol Ring', player='p2'); card(engine, 'Llanowar Elves', player='p3')
    copies = create(engine, spell)
    assert {o.name for o in copies} == {a.name, b.name}
    assert all(combat.has(o, 'haste') and o.is_token for o in copies)
    assert all(o.card.granted_ability_lines == (SACRIFICE_LINE,) for o in copies)
    assert a.controller_id == b.controller_id == 'p2'


def test_targeting_yourself_copies_original_group_once():
    engine, spell = board(); card(engine, 'Grizzly Bears')
    copies = create(engine, spell, 'p1')
    assert len(copies) == 1 and len(named(engine, 'Grizzly Bears')) == 2


def test_empty_creature_group_creates_nothing_and_clears_pending_batch():
    engine, spell = board()
    assert create(engine, spell) == [] and engine.state.pending_token_batch is None


def test_group_is_evaluated_at_resolution():
    engine, spell = board()
    card(engine, 'Grizzly Bears', player='p2')
    from tests.support.deck_batch import RICH, main_phase
    main_phase(engine); engine.state.players[0].mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.players[0], spell, targets=[engine.state.players[1]])
    card(engine, 'Ornithopter', player='p2')
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token]) == 2


def test_creatures_are_not_targets_so_shroud_does_not_prevent_copying():
    engine, spell = board(); original = card(engine, 'Grizzly Bears', player='p2')
    original.temp_keywords.add('shroud')
    assert len(create(engine, spell)) == 1


def test_no_planeswalker_at_end_step_sacrifices_copies():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]
    step(engine, 'end')
    assert token not in engine.state.battlefield
    assert len(named(engine, 'Grizzly Bears', 'p2')) == 1


def test_controlling_planeswalker_prevents_trigger_entirely():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; planeswalker(engine)
    engine.interactive_priority = True
    step(engine, 'end')
    assert not engine.state.stack and token in engine.state.battlefield


def test_other_players_planeswalker_does_not_protect_tokens():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; planeswalker(engine, 'p2')
    step(engine, 'end')
    assert token not in engine.state.battlefield


def test_condition_is_rechecked_when_trigger_resolves():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1'))
    engine.rules.put_triggers_on_stack(); assert engine.state.stack
    planeswalker(engine)
    engine.resolve_until_stable()
    assert token in engine.state.battlefield


def test_planeswalker_lost_after_end_step_does_not_create_missing_trigger():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; walker = planeswalker(engine)
    step(engine, 'end'); engine.rules.exile(walker); engine.resolve_until_stable()
    assert token in engine.state.battlefield
    step(engine, 'end', player='p2')
    assert token not in engine.state.battlefield


def test_condition_uses_current_controller_at_trigger_time():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; planeswalker(engine)
    token.controller_id = 'p3'
    step(engine, 'end', player='p2')
    assert token not in engine.state.battlefield


def test_new_controllers_planeswalker_prevents_trigger():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; planeswalker(engine, 'p3')
    token.controller_id = 'p3'
    step(engine, 'end', player='p2')
    assert token in engine.state.battlefield


def test_countering_end_step_trigger_keeps_token_until_later_end_step():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    assert token in engine.state.battlefield
    step(engine, 'end', player='p2')
    assert token not in engine.state.battlefield


def test_losing_control_after_trigger_cannot_sacrifice_opponents_token():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1'))
    engine.rules.put_triggers_on_stack(); token.controller_id = 'p3'
    engine.resolve_until_stable()
    assert token in engine.state.battlefield


def test_copied_tokens_enter_simultaneously_and_see_each_other():
    engine, spell = board()
    card(engine, 'Soul Warden', player='p2'); card(engine, 'Grizzly Bears', player='p2')
    before = engine.state.players[0].life
    create(engine, spell)
    assert engine.state.players[0].life == before + 1


def test_earlier_token_also_sees_later_entry_when_order_is_reversed():
    engine, spell = board()
    card(engine, 'Grizzly Bears', player='p2'); card(engine, 'Soul Warden', player='p2')
    before = engine.state.players[0].life
    create(engine, spell)
    assert engine.state.players[0].life == before + 1


def test_copies_keep_copiable_abilities_not_counters_or_temporary_pumps():
    engine, spell = board(); original = card(engine, 'Grizzly Bears', player='p2')
    original.add_counters('+1/+1', 3); original.temp_power = 5; engine.recompute_continuous_effects()
    token = create(engine, spell)[0]
    assert token.power == 2 and not token.counters


def test_further_copy_inherits_intrinsic_haste_and_sacrifice_ability():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; copy = engine.rules.copy_permanent('p1', token)[0]
    assert combat.has(copy, 'haste') and copy.card.granted_ability_lines == (SACRIFICE_LINE,)
    step(engine, 'end')
    assert token not in engine.state.battlefield and copy not in engine.state.battlefield


def test_clone_preserves_token_trigger_and_copiable_values():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]
    clone = GameEngine(engine.state.clone()); step(clone, 'end')
    assert clone.state.find_object(token.instance_id) not in clone.state.battlefield
    assert token in engine.state.battlefield


def test_entry_choices_finish_before_any_new_token_enters():
    engine, spell = board()
    card(engine, 'Adaptive Automaton', player='p2'); card(engine, 'Grizzly Bears', player='p2')
    create(engine, spell)
    assert engine.state.pending_choice['kind'] == 'choose_creature_type'
    assert not any(o.is_token for o in engine.state.battlefield)
    assert len(engine.state.pending_token_batch['objects']) == 2
    engine.resolve_pending_choice('bear'); engine.resolve_until_stable()
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == 2 and engine.state.pending_token_batch is None
    assert next(o for o in tokens if o.name == 'Adaptive Automaton').chosen_type == 'bear'


def test_clone_of_paused_entry_batch_finishes_in_its_own_state():
    engine, spell = board()
    card(engine, 'Adaptive Automaton', player='p2'); card(engine, 'Grizzly Bears', player='p2')
    create(engine, spell)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice('bear'); clone.resolve_until_stable()
    assert len([o for o in clone.state.battlefield if o.is_token]) == 2
    assert not any(o.is_token for o in engine.state.battlefield)
    assert engine.state.pending_choice['kind'] == 'choose_creature_type'
    assert clone.state.pending_token_batch is None


def test_token_creation_replacement_applies_before_group_entry():
    engine, spell = board()
    card(engine, 'Doubling Season'); card(engine, 'Grizzly Bears', player='p2')
    tokens = create(engine, spell)
    assert len(tokens) == 2
    assert all(combat.has(o, 'haste') and o.card.granted_ability_lines == (SACRIFICE_LINE,) for o in tokens)


def test_second_cast_can_copy_existing_tokens_and_adds_another_ability_instance():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    first = create(engine, spell)[0]
    second_spell = card(engine, 'Face Yourself', zone=Zone.HAND)
    create(engine, second_spell, 'p1')
    second = next(o for o in engine.state.battlefield if o.is_token and o is not first)
    assert len(second.triggered_abilities) == 2
    assert second.card.granted_ability_lines == (SACRIFICE_LINE, SACRIFICE_LINE)


def test_haste_persists_past_cleanup_when_planeswalker_keeps_token_alive():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    token = create(engine, spell)[0]; planeswalker(engine)
    step(engine, 'end'); engine._step_cleanup()
    assert token in engine.state.battlefield and combat.has(token, 'haste')


def test_countering_spell_creates_no_tokens_or_pending_batch():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    from tests.support.deck_batch import RICH, main_phase
    main_phase(engine); engine.state.players[0].mana_pool.add_many(RICH)
    engine.cast_spell(engine.state.players[0], spell, targets=[engine.state.players[1]])
    engine.rules.counter_spell(spell); engine.resolve_until_stable()
    assert not any(o.is_token for o in engine.state.battlefield)
    assert engine.state.pending_token_batch is None


def test_transformed_creature_copy_uses_current_face():
    engine, spell = board()
    original = card(engine, 'Delver of Secrets // Insectile Aberration', player='p2')
    engine.rules.transform_permanent(original); engine.recompute_continuous_effects()
    assert original.name == 'Insectile Aberration'
    token = create(engine, spell)[0]
    assert token.name == 'Insectile Aberration' and token.power == 3 and combat.has(token, 'flying')


def test_duplicate_added_abilities_make_independent_counterable_triggers():
    engine, spell = board(); card(engine, 'Grizzly Bears', player='p2')
    first = create(engine, spell)[0]
    other = card(engine, 'Face Yourself', zone=Zone.HAND); create(engine, other, 'p1')
    second = next(o for o in engine.state.battlefield if o.is_token and o is not first)
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1'))
    engine.rules.put_triggers_on_stack()
    triggers = [i for i in engine.state.stack if i.source is second]
    assert len(triggers) == 2
    engine.rules.counter_spell(triggers[0]); engine.resolve_until_stable()
    assert second not in engine.state.battlefield


def test_prevented_token_creation_continues_remaining_jobs_and_clears_batch():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    from mtg_analyzer.models.game.events import EventType
    engine, spell = board()
    card(engine, 'Grizzly Bears', player='p2'); card(engine, 'Ornithopter', player='p2')
    marker = filler(engine, 'Token prevention', type_line='Enchantment')
    seen = []
    def prevent(event, context):
        seen.append(event.get('token_name'))
        return None
    marker.replacement_effects.append(ReplacementEffect(EventType.CREATE_TOKENS, prevent, source=marker))
    assert create(engine, spell) == []
    assert len(seen) == 2 and engine.state.pending_token_batch is None
