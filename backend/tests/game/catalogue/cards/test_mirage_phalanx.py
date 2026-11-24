"""Mirage Phalanx pairs, grants two self-copy triggers and exiles the haste copies at combat end."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, enter, filler, game, named, step
from tests.support.star_trek import advance_to


def board(paired=True, partner_name='Grizzly Bears'):
    engine = game(players=3, library=40); advance_to(engine, 'main1')
    partner = card(engine, partner_name)
    source = card(engine, 'Mirage Phalanx')
    if paired:
        enter(engine, source)
        while engine.state.pending_choice:
            choice = engine.state.pending_choice
            if choice['kind'] == 'order_triggers':
                engine.resolve_pending_choice(str(choice['options'][0]['id']))
            else:
                wanted = partner.instance_id if choice.get('source_id') == source.instance_id else source.instance_id
                option = next(o for o in choice['options'] if o.get('instance_id') == wanted)
                engine.resolve_pending_choice(str(option['id']))
        engine.resolve_until_stable()
        assert source.paired_with == partner.instance_id
    return engine, source, partner


def copies(engine):
    return [obj for obj in engine.state.battlefield if obj.is_token]


def combat_start(engine, player='p1'):
    engine.state.active_player_index = next(i for i, p in enumerate(engine.state.players) if p.id == player)
    step(engine, 'begin_combat', player=player)


def test_fresh_specs_original_soulbond_and_pair_grants():
    engine, source, partner = board(); a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert combat.has(source, 'soulbond')
    assert len(source.granted_triggered_abilities) == len(partner.granted_triggered_abilities) == 1


def test_beginning_of_own_combat_creates_copy_of_each_paired_creature():
    engine, source, partner = board(); combat_start(engine)
    tokens = copies(engine)
    assert len(tokens) == 2 and {t.name for t in tokens} == {source.name, partner.name}
    assert all(combat.has(t, 'haste') and not combat.has(t, 'soulbond') for t in tokens)
    assert all(t.paired_with is None for t in tokens)
    assert engine.state.pending_choice is None and len(engine.state.delayed_triggers) == 2


def test_tokens_are_exiled_at_end_of_combat_not_end_step():
    engine, source, partner = board(); combat_start(engine); tokens = copies(engine)
    step(engine, 'end_combat')
    assert not copies(engine) and all(t not in engine.state.battlefield for t in tokens)
    assert source in engine.state.battlefield and partner in engine.state.battlefield


def test_unpaired_phalanx_grants_no_combat_ability_and_makes_no_copy():
    engine, source, partner = board(paired=False); combat_start(engine)
    assert not copies(engine) and not source.granted_triggered_abilities and not partner.granted_triggered_abilities


def test_other_players_combat_does_not_trigger_pair():
    engine, source, partner = board(); combat_start(engine, 'p2')
    assert not copies(engine)


def test_copy_keyword_removal_is_inherited_by_a_further_copy():
    engine, source, partner = board(); combat_start(engine)
    token = next(t for t in copies(engine) if t.name == source.name)
    copy = engine.rules.copy_permanent('p1', token)[0]
    assert combat.has(copy, 'haste') and not combat.has(copy, 'soulbond')
    assert copy.card.copy_removed_keywords == ('soulbond',)
    assert not copy.triggered_abilities


def test_copy_keyword_removal_survives_card_serialization():
    engine, source, partner = board(); combat_start(engine)
    token = next(t for t in copies(engine) if t.name == source.name)
    restored = Card.from_dict(token.card.to_dict())
    assert restored.copy_removed_keywords == ('soulbond',)
    assert not any(s.keyword and s.keyword.get('name') == 'soulbond' for s in specs_for(restored))


def test_partner_with_soulbond_also_loses_soulbond_on_its_copy():
    engine, source, partner = board(partner_name='Silverblade Paladin'); combat_start(engine)
    assert len(copies(engine)) == 2 and all(not combat.has(t, 'soulbond') for t in copies(engine))
    assert engine.state.pending_choice is None


def test_pair_breaks_when_partner_leaves_and_grants_disappear():
    engine, source, partner = board()
    engine.rules.exile(partner); engine.resolve_until_stable(); engine.recompute_continuous_effects()
    assert source.paired_with is None
    combat_start(engine)
    assert not copies(engine)


def test_pair_breaks_when_source_leaves():
    engine, source, partner = board()
    engine.rules.exile(source); engine.resolve_until_stable(); engine.recompute_continuous_effects()
    assert partner.paired_with is None and not partner.granted_triggered_abilities


def test_copies_keep_printed_stats_without_original_counters():
    engine, source, partner = board()
    source.add_counters('+1/+1', 3); engine.recompute_continuous_effects()
    combat_start(engine)
    token = next(t for t in copies(engine) if t.name == source.name)
    assert token.power == source.card.power and not token.counters


def test_pairing_can_be_declined_at_resolution():
    engine, source, partner = board(paired=False)
    enter(engine, source)
    assert engine.state.pending_choice['kind'] == 'choose_objects'
    engine.resolve_pending_choice('decline')
    combat_start(engine)
    assert source.paired_with is None and not copies(engine)


def test_later_entering_creature_is_the_only_partner_for_that_trigger():
    engine, source, old = board(paired=False)
    newcomer = card(engine, 'Llanowar Elves'); enter(engine, newcomer)
    choice = engine.state.pending_choice
    ids = {o.get('instance_id') for o in choice['options']}
    assert newcomer.instance_id in ids and old.instance_id not in ids
    engine.resolve_pending_choice(str(newcomer.instance_id)); engine.resolve_until_stable()
    assert source.paired_with == newcomer.instance_id and old.paired_with is None


def test_self_entry_lets_controller_choose_any_eligible_partner():
    engine, source, old = board(paired=False)
    other = card(engine, 'Llanowar Elves'); enter(engine, source)
    ids = {o.get('instance_id') for o in engine.state.pending_choice['options']}
    assert old.instance_id in ids and other.instance_id in ids
    engine.resolve_pending_choice(str(other.instance_id)); engine.resolve_until_stable()
    assert source.paired_with == other.instance_id and old.paired_with is None


def test_no_other_creature_means_soulbond_does_not_trigger():
    engine, source, partner = board(paired=False)
    engine.rules.exile(partner); enter(engine, source)
    assert engine.state.pending_choice is None and source.paired_with is None


def test_pair_breaks_if_partner_changes_controller():
    engine, source, partner = board(); partner.controller_id = 'p2'
    engine.resolve_until_stable(); engine.recompute_continuous_effects()
    assert source.paired_with is None and partner.paired_with is None
    combat_start(engine)
    assert not copies(engine)


def test_pair_breaks_even_if_both_creatures_change_to_same_new_controller():
    engine, source, partner = board()
    source.controller_id = partner.controller_id = 'p2'
    engine.resolve_until_stable(); engine.recompute_continuous_effects()
    assert source.paired_with is None and partner.paired_with is None
    combat_start(engine, 'p2')
    assert not copies(engine)


def queue_combat_triggers(engine):
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.current_step = 'begin_combat'
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='begin_combat', player_id='p1'))
    engine.rules.put_triggers_on_stack()


def test_breaking_pair_does_not_remove_already_triggered_copy_abilities():
    engine, source, partner = board(); queue_combat_triggers(engine)
    assert len(engine.state.stack) == 2
    source.paired_with = partner.paired_with = None
    engine.recompute_continuous_effects(); engine.resolve_until_stable()
    while engine.state.pending_choice:
        assert engine.state.pending_choice.get('action') == 'soulbond_pair'
        engine.resolve_pending_choice('decline')
    assert len(copies(engine)) == 2


def test_departed_source_copy_trigger_uses_last_known_values():
    engine, source, partner = board(); queue_combat_triggers(engine)
    engine.rules.exile(source); engine.resolve_until_stable()
    tokens = copies(engine)
    assert len(tokens) == 2 and {t.name for t in tokens} == {source.name, partner.name}
    assert all(combat.has(t, 'haste') for t in tokens)


def test_one_countered_combat_trigger_prevents_only_its_copy():
    engine, source, partner = board(); queue_combat_triggers(engine)
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    assert len(copies(engine)) == 1 and len(engine.state.delayed_triggers) == 1


def test_stolen_copies_are_still_exiled_at_combat_end():
    engine, source, partner = board(); combat_start(engine); tokens = copies(engine)
    for token in tokens:
        token.controller_id = 'p2'
    step(engine, 'end_combat')
    assert all(t not in engine.state.battlefield for t in tokens)


def test_countered_delayed_exile_is_not_repeated_and_haste_remains_intrinsic():
    engine, source, partner = board(); combat_start(engine); tokens = copies(engine)
    engine._fire_delayed_triggers('end_combat')
    while engine.state.stack:
        engine.rules.counter_spell(engine.state.stack[-1])
    engine.resolve_until_stable(); engine._step_cleanup()
    assert all(t in engine.state.battlefield and combat.has(t, 'haste') for t in tokens)
    assert not engine.state.delayed_triggers


def test_further_copy_does_not_inherit_originals_delayed_exile():
    engine, source, partner = board(); combat_start(engine)
    token = next(t for t in copies(engine) if t.name == source.name)
    further = engine.rules.copy_permanent('p1', token)[0]
    step(engine, 'end_combat')
    assert copies(engine) == [further] and not combat.has(further, 'soulbond')


def test_each_additional_own_combat_makes_a_new_pair_of_copies():
    engine, source, partner = board(); combat_start(engine); step(engine, 'end_combat')
    combat_start(engine)
    assert len(copies(engine)) == 2


def test_two_paired_phalanxes_grant_two_abilities_to_each_member():
    engine, source, partner = board(partner_name='Mirage Phalanx')
    assert len(source.granted_triggered_abilities) == len(partner.granted_triggered_abilities) == 2
    combat_start(engine)
    assert len(copies(engine)) == 4 and all(not combat.has(t, 'soulbond') for t in copies(engine))


def test_undo_clone_preserves_pair_and_keyword_removal_and_exile_triggers():
    from mtg_analyzer.game.game_engine import GameEngine
    engine, source, partner = board(); combat_start(engine); tokens = copies(engine)
    clone = GameEngine(engine.state.clone())
    assert clone.state.find_object(source.instance_id).paired_with == partner.instance_id
    step(clone, 'end_combat')
    assert not copies(clone) and len(copies(engine)) == 2


def test_pairing_trigger_can_be_countered_before_optional_partner_choice():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, source, partner = board(paired=False)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
        controller_id='p1', object=source.name, object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is None and len(engine.state.stack) == 1
    engine.rules.counter_spell(engine.state.stack[-1]); engine.resolve_until_stable()
    assert source.paired_with is None and engine.state.pending_choice is None


def test_departed_soulbond_source_does_not_pair_from_exile():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, source, partner = board(paired=False)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
        controller_id='p1', object=source.name, object_types=sorted(source.type_words)))
    engine.rules.put_triggers_on_stack(); engine.rules.exile(source); engine.resolve_until_stable()
    assert source.paired_with is None and partner.paired_with is None and engine.state.pending_choice is None


def test_copy_of_departed_partner_uses_form_before_exile_reset():
    engine, source, partner = board(paired=False, partner_name='Clone')
    prototype = card(engine, 'Grizzly Bears')
    engine.rules.become_copy(partner, prototype); engine.recompute_continuous_effects()
    enter(engine, source)
    engine.resolve_pending_choice(str(partner.instance_id)); engine.resolve_until_stable()
    queue_combat_triggers(engine)
    engine.rules.exile(partner); engine.resolve_until_stable()
    while engine.state.pending_choice:
        assert engine.state.pending_choice.get('action') == 'soulbond_pair'
        engine.resolve_pending_choice('decline')
    assert partner.name == 'Clone'
    assert {t.name for t in copies(engine)} == {'Mirage Phalanx', 'Grizzly Bears'}
    assert engine.state.pending_choice is None


def test_still_present_partner_is_copied_using_new_copiable_values_at_resolution():
    engine, source, partner = board(); queue_combat_triggers(engine)
    prototype = card(engine, 'Llanowar Elves')
    engine.rules.become_copy(partner, prototype); engine.recompute_continuous_effects()
    engine.resolve_until_stable()
    assert {t.name for t in copies(engine)} == {'Mirage Phalanx', 'Llanowar Elves'}


def test_later_copy_exception_can_explicitly_add_soulbond_back():
    engine, source, partner = board(); combat_start(engine)
    token = next(t for t in copies(engine) if t.name == source.name)
    new_copy = engine.rules.copy_permanent('p1', token, add_keywords=['Soulbond'])[0]
    assert combat.has(new_copy, 'soulbond') and new_copy.card.copy_removed_keywords == ()


def test_real_cast_has_soulbond_and_pairs_with_existing_creature():
    from tests.support.deck_batch import cast
    engine = game(players=3, library=40); advance_to(engine, 'main1')
    partner = card(engine, 'Grizzly Bears')
    source = card(engine, 'Mirage Phalanx', zone=Zone.HAND)
    cast(engine, source)
    assert engine.state.pending_choice['kind'] == 'choose_objects'
    engine.resolve_pending_choice(str(partner.instance_id)); engine.resolve_until_stable()
    assert source.paired_with == partner.instance_id and combat.has(source, 'soulbond')
    combat_start(engine)
    assert len(copies(engine)) == 2


def test_soulbond_after_undo_reads_restored_objects_not_original_state():
    from mtg_analyzer.game.game_engine import GameEngine
    engine, source, partner = board(paired=False)
    clone = GameEngine(engine.state.clone())
    newcomer = card(clone, 'Llanowar Elves'); enter(clone, newcomer)
    assert clone.state.pending_choice['action'] == 'soulbond_pair'
    clone.resolve_pending_choice(str(newcomer.instance_id)); clone.resolve_until_stable()
    assert clone.state.find_object(source.instance_id).paired_with == newcomer.instance_id
    assert source.paired_with is None and engine.state.pending_choice is None


def test_pending_soulbond_choice_survives_undo_independently():
    from mtg_analyzer.game.game_engine import GameEngine
    engine, source, partner = board(paired=False); enter(engine, source)
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(partner.instance_id)); clone.resolve_until_stable()
    assert clone.state.find_object(source.instance_id).paired_with == partner.instance_id
    assert source.paired_with is None and engine.state.pending_choice['action'] == 'soulbond_pair'
