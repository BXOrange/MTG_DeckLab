"""PAR-223: continuous lifetimes compose with subjects and survive clone/undo."""
import pytest

from mtg_analyzer.game import durations
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.game import creature
from tests.test_par210_player_references import game, board, DB


def run(eng, source, text, targets=(), previous=()):
    specs = parse_effect_body(text, reading=ClauseReading(previous_subject=bool(previous)))
    assert specs is not None, text
    context = eng.rules.context
    context.previous_targets = list(previous)
    for effect in build_effects(specs, source):
        effect.apply(context, list(targets))
    eng.recompute_continuous_effects()
    return specs


@pytest.mark.parametrize('name', ['Aegis Angel', 'Kyodai, Soul of Kamigawa', 'Endoskeleton',
    "Ashnod's Battle Gear", 'Flowstone Armor', 'Spirit Shield', "Tawnos's Weaponry", 'Zelyon Sword',
    'Thran Weaponry', 'Erhnam Djinn', 'Xenic Poltergeist', 'Quicksmith Spy', 'Quicksmith Rebel',
    'Galvanic Relay', 'Immovable Rod'])
def test_real_card_is_modeled(name):
    result = parse_oracle(DB.get_card(name))
    assert result.modeled, result.unclaimed


@pytest.mark.parametrize('text', [
    'target creature gets +2/+2 for as long as the moon is blue',
    'draw a card until your next upkeep',
    'destroy target creature until your next end step',
    'target creature gets +2/+2 until your next upkeep until end of turn',
    'target artifact gains "do something impossible" for as long as you control ~',
])
def test_unrepresentable_body_or_clock_fails_closed(text):
    assert parse_effect_body(text) is None


@pytest.mark.parametrize('clock,window', [('until your next upkeep', 'upkeep'),
    ('until your next end step', 'end_step')])
def test_step_clock_ignores_other_player_and_ends_before_step_triggers(clock, window):
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Recipient', power=2, toughness=2))
    run(eng, source, f'target creature gets +2/+2 {clock}', [victim])
    assert victim.power == 4
    durations.sweep(eng.state, 'cleanup')
    eng.state.active_player_index = 1
    assert not durations.sweep(eng.state, window)
    assert victim.power == 4
    eng.state.active_player_index = 0
    assert durations.sweep(eng.state, window)
    eng.recompute_continuous_effects()
    assert victim.power == 2


def test_source_tapped_window_ends_permanently_and_does_not_follow_a_new_visit():
    eng = game()
    source = board(eng, DB.get_card('Endoskeleton'))
    victim = board(eng, creature('Recipient', power=2, toughness=2))
    source.tapped = True
    source.activated_abilities[0].effects[0].apply(eng.rules.context, [victim])
    assert victim.toughness == 5
    source.tapped = False
    eng.recompute_continuous_effects()
    assert victim.toughness == 2
    source.tapped = True
    eng.recompute_continuous_effects()
    assert victim.toughness == 2
    run(eng, source, 'target creature gets +0/+3 for as long as ~ remains tapped', [victim])
    source.zone_incarnation += 1
    eng.recompute_continuous_effects()
    assert victim.toughness == 2


def test_source_control_and_presence_are_distinct_and_an_ended_window_cannot_start():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Recipient', power=2, toughness=2))
    run(eng, source, 'target creature gains indestructible for as long as you control ~', [victim])
    assert 'indestructible' in victim.granted_keywords
    source.controller_id = 'p2'
    eng.recompute_continuous_effects()
    assert 'indestructible' not in victim.granted_keywords
    source.controller_id = 'p1'
    eng.recompute_continuous_effects()
    assert 'indestructible' not in victim.granted_keywords
    source.tapped = False
    run(eng, source, 'target creature gets +2/+2 for as long as ~ remains tapped', [victim])
    source.tapped = True
    eng.recompute_continuous_effects()
    assert victim.power == 2


def test_group_is_fixed_at_resolution_and_survives_clone():
    eng = game()
    source = board(eng, DB.get_card('Thran Weaponry'))
    victim = board(eng, creature('Recipient', power=2, toughness=2))
    source.tapped = True
    source.activated_abilities[0].effects[0].apply(eng.rules.context)
    assert victim.power == 4
    late = board(eng, creature('Late', power=2, toughness=2))
    eng.recompute_continuous_effects()
    assert late.power == 2
    clone = eng.state.clone()
    clone.find_object(source.instance_id).tapped = False
    durations.sweep(clone, 'recompute')
    assert not clone.floating_statics
    assert eng.state.floating_statics


def test_counter_condition_is_on_the_recipient_not_the_source_and_never_restarts():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Recipient'))
    victim.counters['duty'] = 1
    run(eng, source, 'that creature gains flying for as long as that creature has a duty counter on it', previous=[victim])
    assert 'flying' in victim.granted_keywords
    eng.rules.exile(source)
    eng.recompute_continuous_effects()
    assert 'flying' in victim.granted_keywords
    victim.counters.clear()
    eng.recompute_continuous_effects()
    assert 'flying' not in victim.granted_keywords
    victim.counters['duty'] = 1
    eng.recompute_continuous_effects()
    assert 'flying' not in victim.granted_keywords


def test_monarch_condition_expires_irrevocably():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Recipient'))
    eng.state.monarch_id = 'p1'
    run(eng, source, 'target creature gains flying for as long as you are the monarch', [victim])
    assert 'flying' in victim.granted_keywords
    eng.state.monarch_id = 'p2'
    eng.recompute_continuous_effects()
    assert 'flying' not in victim.granted_keywords
    eng.state.monarch_id = 'p1'
    eng.recompute_continuous_effects()
    assert 'flying' not in victim.granted_keywords


def test_prevention_outlives_cleanup_but_not_the_holders_next_turn():
    eng = game()
    source = board(eng, creature('Source'))
    dealer = board(eng, creature('Dealer'), 'p2')
    victim = eng.state.player_by_id('p1')
    run(eng, source, 'prevent all damage that would be dealt by target creature until your next turn', [dealer])
    eng.rules.deal_damage(victim, 3, source=dealer)
    assert victim.life == 20
    eng._step_cleanup()
    eng.state.active_player_index = 1
    durations.sweep(eng.state, 'turn_begin')
    eng.rules.deal_damage(victim, 3, source=dealer)
    assert victim.life == 20
    eng.state.active_player_index = 0
    durations.sweep(eng.state, 'turn_begin')
    eng.rules.deal_damage(victim, 3, source=dealer)
    assert victim.life == 17


def test_exact_exile_play_end_step_and_next_turn_only_window():
    eng = game()
    source = board(eng, creature('Source'))
    p1 = eng.state.player_by_id('p1')
    run(eng, source, 'exile the top card of your library. during your next turn, you may play that card')
    exiled = p1.exile[-1]
    assert not eng._has_temp_play_permission(exiled, p1)
    eng._step_cleanup()
    assert not eng._has_temp_play_permission(exiled, p1)
    eng.state.active_player_index = 1
    assert not eng._has_temp_play_permission(exiled, p1)
    eng.state.active_player_index = 0
    eng.state.internal_turn.number += 2
    assert eng._has_temp_play_permission(exiled, p1)
    eng._step_cleanup()
    assert not eng._has_temp_play_permission(exiled, p1)
    eng.state.active_player_index = 1
    run(eng, source, 'exile the top card of your library. you may play that card until your next end step')
    exiled = p1.exile[-1]
    eng._step_cleanup()
    assert eng._has_temp_play_permission(exiled, p1)
    durations.sweep(eng.state, 'end_step')
    assert eng._has_temp_play_permission(exiled, p1)
    eng.state.active_player_index = 0
    durations.sweep(eng.state, 'end_step')
    assert not eng._has_temp_play_permission(exiled, p1)


def test_timed_control_preserves_independent_later_control_effect():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Victim'), 'p2')
    run(eng, source, 'gain control of target creature until your next upkeep', [victim])
    assert victim.controller_id == 'p1' and 'haste' not in victim.temp_keywords
    run(eng, source, 'gain control of target creature', [victim])
    durations.sweep(eng.state, 'upkeep')
    assert victim.controller_id == 'p1'


def test_linked_attachment_copy_ends_when_detached_and_keeps_original_host():
    eng = game()
    equipment = board(eng, DB.get_card('Assimilation Aegis'))
    result = parse_oracle(equipment.card)
    assert result.modeled, result.unclaimed
    host = board(eng, creature('Host', power=2, toughness=2))
    template = board(eng, creature('Template', power=5, toughness=5), 'p2')
    # Use the real entry ability's exile and source-linked pool.
    for effect in equipment.triggered_abilities[0].effects:
        effect.apply(eng.rules.context, [template])
    assert template.zone == Zone.EXILE
    assert eng.rules.attach_to_target(equipment, host, check_control=False)
    eng.resolve_until_stable()
    assert host.name == 'Template' and host.power == 5
    other = board(eng, creature('Other host', power=3, toughness=3))
    eng.rules.attach_to_target(equipment, other, check_control=False)
    eng.recompute_continuous_effects()
    assert host.name == 'Host' and host.power == 2
    eng.resolve_until_stable()
    assert other.name == 'Template'
    eng.rules.return_to_hand(equipment)
    eng.recompute_continuous_effects()
    assert other.name == 'Other host'


def test_counter_bound_quoted_ability_is_removed_when_counter_is_removed():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Recipient'))
    victim.counters['bounty'] = 1
    run(eng, source, 'that creature has "when ~ dies, draw a card" for as long as that creature has a bounty counter on it', previous=[victim])
    assert victim.granted_triggered_abilities
    victim.counters.clear()
    eng.recompute_continuous_effects()
    assert not victim.granted_triggered_abilities


def test_long_lived_prevention_and_permission_clone_retains_clocks():
    eng = game()
    source = board(eng, creature('Source'))
    dealer = board(eng, creature('Dealer'), 'p2')
    run(eng, source, 'prevent all damage target creature would deal until your next upkeep', [dealer])
    run(eng, source, 'exile the top card of your library. you may play that card until your next end step')
    clone = eng.state.clone()
    assert clone.temp_play_permission_clocks == eng.state.temp_play_permission_clocks
    durations.sweep(clone, 'upkeep')
    assert not any(getattr(e, 'duration', None) for p in clone.players for e in p.player_effects)
    assert any(getattr(e, 'duration', None) for p in eng.state.players for e in p.player_effects)


def test_trailing_clock_does_not_retime_an_earlier_permanent_animation():
    from mtg_analyzer.models.cards.card import Card
    eng = game()
    source = board(eng, DB.get_card('Rootwise Survivor'))
    land = board(eng, Card(id='land', name='Land', type_line='Land', is_land=True))
    source.tapped = True
    for effect in source.triggered_abilities[0].effects:
        effect.apply(eng.rules.context, [land])
    eng.recompute_continuous_effects()
    assert land.is_creature and 'haste' in land.granted_keywords
    durations.sweep(eng.state, 'turn_begin')
    eng.recompute_continuous_effects()
    assert land.is_creature and 'haste' not in land.granted_keywords


def test_recipient_prevention_has_the_same_clock_as_source_prevention():
    eng = game()
    source = board(eng, creature('Source'))
    victim = board(eng, creature('Victim', power=4, toughness=4))
    dealer = board(eng, creature('Dealer'), 'p2')
    run(eng, source, 'prevent all damage that would be dealt to target creature until your next upkeep', [victim])
    eng.rules.deal_damage(victim, 1, source=dealer)
    assert victim.damage_marked == 0
    eng._step_cleanup()
    eng.rules.deal_damage(victim, 1, source=dealer)
    assert victim.damage_marked == 0
    durations.sweep(eng.state, 'upkeep')
    eng.rules.deal_damage(victim, 1, source=dealer)
    assert victim.damage_marked == 1


def test_source_bound_play_permission_ends_when_source_control_is_lost():
    eng = game()
    source = board(eng, creature('Source'))
    p1 = eng.state.player_by_id('p1')
    run(eng, source, 'exile the top card of your library. you may play that card for as long as you control ~')
    obj = p1.exile[-1]
    assert eng._has_temp_play_permission(obj, p1)
    source.controller_id = 'p2'
    assert not eng._has_temp_play_permission(obj, p1)
    source.controller_id = 'p1'
    assert not eng._has_temp_play_permission(obj, p1)


def test_optional_attachment_copy_choice_survives_clone_and_rejects_moved_host():
    from mtg_analyzer.game.game_engine import GameEngine
    eng = game()
    equipment = board(eng, DB.get_card('Blade of Shared Souls'))
    host = board(eng, creature('Host', power=2, toughness=2))
    template = board(eng, creature('Template', power=5, toughness=5))
    eng.rules.attach_to_target(equipment, host, check_control=False)
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    if choice:
        # Choose the copy's announced target; the optional decision follows at resolution.
        option = next(o['id'] for o in choice['options'] if 'Template' in o['label'])
        eng.resolve_pending_choice(option)
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'choose_objects'
    clone = GameEngine(eng.state.clone())
    eng.rules.return_to_hand(host)
    option = eng.state.pending_choice['options'][0]['id']
    eng.resolve_pending_choice(option)
    eng.resolve_until_stable()
    assert host.name == 'Host'
    clone.resolve_pending_choice(clone.state.pending_choice['options'][0]['id'])
    clone.resolve_until_stable()
    assert clone.state.find_object(host.instance_id).name == 'Template'


def test_old_attachment_trigger_cannot_start_after_detach_and_reattach_to_same_host():
    eng = game()
    equipment = board(eng, DB.get_card('Assimilation Aegis'))
    host = board(eng, creature('Host'))
    template = board(eng, creature('Template'))
    for effect in equipment.triggered_abilities[0].effects:
        effect.apply(eng.rules.context, [template])
    eng.rules.attach_to_target(equipment, host, check_control=False)
    old_event = eng.state.event_log[-1]
    equipment.attached_to = None
    eng.rules.attach_to_target(equipment, host, check_control=False)
    context = eng.rules.context
    context.trigger_event = old_event.data
    for effect in equipment.triggered_abilities[1].effects:
        effect.apply(context)
    assert host.name == 'Host'


def test_quicksmith_spy_grants_a_usable_tap_draw_and_ends_on_control_loss():
    from mtg_analyzer.models.cards.card import Card
    eng = game()
    source = board(eng, DB.get_card('Quicksmith Spy'))
    recipient = board(eng, Card(id='artifact', name='Artifact', type_line='Artifact'))
    for effect in source.triggered_abilities[0].effects:
        effect.apply(eng.rules.context, [recipient])
    eng.recompute_continuous_effects()
    assert recipient.granted_activated_abilities
    player = eng.state.player_by_id('p1')
    before = len(player.hand)
    eng.activate_ability(player, recipient, 0)
    eng.resolve_until_stable()
    assert len(player.hand) == before + 1
    source.controller_id = 'p2'
    eng.recompute_continuous_effects()
    assert not recipient.granted_activated_abilities


def test_erhnam_forestwalk_survives_other_upkeeps_and_ends_at_yours():
    eng = game()
    source = board(eng, DB.get_card('Erhnam Djinn'))
    recipient = board(eng, creature('Recipient'), 'p2')
    for effect in source.triggered_abilities[0].effects:
        effect.apply(eng.rules.context, [recipient])
    eng.recompute_continuous_effects()
    assert 'forestwalk' in recipient.granted_keywords
    eng.state.active_player_index = 1
    durations.sweep(eng.state, 'upkeep')
    eng.recompute_continuous_effects()
    assert 'forestwalk' in recipient.granted_keywords
    eng.state.active_player_index = 0
    durations.sweep(eng.state, 'upkeep')
    eng.recompute_continuous_effects()
    assert 'forestwalk' not in recipient.granted_keywords


@pytest.mark.parametrize('text', [
    'target creature gains flying for as long as that land has a duty counter on it',
    '~ gains flying for as long as that creature has a duty counter on it',
])
def test_counter_condition_cannot_silently_refer_to_a_different_object(text):
    assert parse_effect_body(text) is None


def test_target_announcement_is_not_a_continuous_effect():
    assert parse_effect_body('choose target creature until your next upkeep') is None
