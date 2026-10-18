"""Zone-bound grants compose trigger heads, optional bodies and measured returns."""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.scryfall_client import card_from_scryfall_data
from test_mec106_gift import _engine, _bf


COSIMA = ('At the beginning of your upkeep, you may exile Cosima. If you do, it gains '
    '"Whenever a land you control enters, if Cosima is exiled, you may put a voyage counter on it. '
    "If you don't, return Cosima to the battlefield with X +1/+1 counters on it and draw X cards, "
    'where X is the number of voyage counters on it."')


def _source(eng, owner='p1', text=COSIMA, name='Cosima'):
    card = Card(id=name, name=name, type_line='Legendary Creature — God', is_creature=True,
                power=2, toughness=4, oracle_text=text)
    assert parse_oracle(card).modeled
    return _bf(eng, card, owner)


def _upkeep(eng, accept=True):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.resolve_until_stable()
    assert eng.state.pending_choice and eng.state.pending_choice['kind'] == 'trigger_target'
    eng.resolve_pending_choice('do' if accept else 'decline')


def _land(eng, who='p1'):
    land = _bf(eng, Card(id='land', name='Land', type_line='Land', is_land=True), who)
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=land.instance_id,
                                  controller_id=who, object_types=['land']))
    eng.resolve_until_stable()
    return land


def test_cosima_optional_exile_then_counters_and_measured_return():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng, False)
    assert source.zone == Zone.BATTLEFIELD and not eng.state.turn_scoped_triggers
    _upkeep(eng)
    assert source.zone == Zone.EXILE
    for _ in range(2):
        _land(eng)
        assert eng.state.pending_choice['kind'] == 'composite_optional'
        eng.resolve_pending_choice('yes')
    assert source.counters == {'voyage': 2}
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert source.zone == Zone.BATTLEFIELD and source.counters == {'+1/+1': 2}
    assert len(eng.state.player_by_id('p1').hand) == 2
    assert all(not obj.counters for obj in eng.state.battlefield if obj.is_land)


def test_zero_counter_return_adds_no_counter_and_draws_nothing():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert source.zone == Zone.BATTLEFIELD and not source.counters
    assert not eng.state.player_by_id('p1').hand


def test_a_new_exile_visit_does_not_retain_battlefield_counters():
    eng = _engine()
    source = _source(eng)
    source.counters = {'voyage': 3, '+1/+1': 2}
    _upkeep(eng)
    assert source.zone == Zone.EXILE and not source.counters
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert not source.counters and not eng.state.player_by_id('p1').hand


def test_granted_ability_belongs_to_owner_of_stolen_exiled_source():
    eng = _engine()
    source = _source(eng, 'p2')
    source.controller_id = 'p1'
    _upkeep(eng)
    _land(eng, 'p1')
    assert not eng.state.pending_choice
    _land(eng, 'p2')
    assert eng.state.pending_choice['player_id'] == 'p2'
    eng.resolve_pending_choice('yes')
    _land(eng, 'p2')
    eng.resolve_pending_choice('decline')
    assert source.zone == Zone.BATTLEFIELD and source.controller_id == 'p2'
    assert len(eng.state.player_by_id('p2').hand) == 1
    assert not eng.state.player_by_id('p1').hand


def test_zone_grant_survives_turns_and_pending_choice_clones_independently():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    eng.state.internal_turn.number += 2
    _land(eng)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice('decline')
    returned = clone.state.find_object(source.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and not returned.counters
    eng.resolve_pending_choice('yes')
    assert source.zone == Zone.EXILE and source.counters == {'voyage': 1}


def test_grant_cannot_fire_after_exile_visit_changes():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    eng.rules.return_to_hand(source)
    eng.rules.exile(source)
    _land(eng)
    assert not eng.state.pending_choice and not eng.state.turn_scoped_triggers


def test_queued_grant_rechecks_source_visit_at_resolution():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    land = _bf(eng, Card(id='land', name='Land', type_line='Land', is_land=True))
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=land.instance_id,
                                  controller_id='p1', object_types=['land']))
    assert eng.rules.pending_triggers
    eng.rules.return_to_hand(source)
    eng.rules.exile(source)
    eng.resolve_until_stable()
    assert not eng.state.pending_choice and not source.counters


@pytest.mark.parametrize('answer', ['yes', 'decline'])
def test_pending_grant_choice_does_not_act_on_a_revisited_exile_card(answer):
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    _land(eng)
    assert eng.state.pending_choice['kind'] == 'composite_optional'
    eng.rules.return_to_hand(source)
    eng.rules.exile(source)
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(answer)
    copied = clone.state.find_object(source.instance_id)
    assert copied.zone == Zone.EXILE and not copied.counters
    assert not clone.state.player_by_id('p1').hand


def test_stale_upkeep_cannot_exile_a_new_source_visit():
    eng = _engine()
    source = _source(eng)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.rules.exile(source)
    eng.rules.return_from_graveyard(source, 'battlefield')
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice('do')
    assert source.zone == Zone.BATTLEFIELD and not eng.state.turn_scoped_triggers


def test_exile_in_response_does_not_receive_the_unresolved_upkeep_grant():
    eng = _engine()
    source = _source(eng)
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='upkeep', phase='beginning'))
    eng.rules.exile(source)
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice('do')
    assert source.zone == Zone.EXILE and not eng.state.turn_scoped_triggers
    _land(eng)
    assert not eng.state.pending_choice


def test_measured_return_counters_are_present_when_entry_event_fires():
    eng = _engine()
    source = _source(eng)
    _upkeep(eng)
    _land(eng)
    eng.resolve_pending_choice('yes')
    observed = []
    eng.state.subscribe(
        lambda event: observed.append(dict(source.counters))
        if event.type == EventType.ENTERS_BATTLEFIELD
        and event.get('instance_id') == source.instance_id else None)
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert observed == [{'+1/+1': 1}]


def test_entry_choice_finishes_before_measured_draw_and_survives_clone():
    eng = _engine()
    source = _source(eng, text=COSIMA + '\nAs Cosima enters, choose a color.')
    _upkeep(eng)
    _land(eng)
    eng.resolve_pending_choice('yes')
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert eng.state.pending_choice and not eng.state.player_by_id('p1').hand
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice(clone.state.pending_choice['options'][0]['id'])
    returned = clone.state.find_object(source.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.chosen_color
    assert returned.counters == {'+1/+1': 1}
    assert len(clone.state.player_by_id('p1').hand) == 1
    assert not eng.state.player_by_id('p1').hand


def test_entry_counter_replacement_does_not_change_the_captured_draw_amount():
    eng = _engine()
    _bf(eng, Card(id='scales', name='Hardened Scales', type_line='Enchantment', oracle_text=
        'If one or more +1/+1 counters would be put on a creature you control, '
        'that many plus one +1/+1 counters are put on it instead.'))
    source = _source(eng)
    _upkeep(eng)
    _land(eng)
    eng.resolve_pending_choice('yes')
    _land(eng)
    eng.resolve_pending_choice('decline')
    assert source.counters == {'+1/+1': 2}
    assert len(eng.state.player_by_id('p1').hand) == 1


def test_unregistered_counter_and_trigger_body_recombine_without_new_handler():
    eng = _engine()
    text = ('At the beginning of your upkeep, you may exile Voyager. If you do, it gains '
        '"Whenever a creature you control enters, if Voyager is exiled, you may put a dream counter on it. '
        "If you don't, return Voyager to the battlefield with X stun counters on it and gain X life, "
        'where X is the number of dream counters on it."')
    source = _source(eng, text=text, name='Voyager')
    _upkeep(eng)
    for answer in ['yes', 'decline']:
        entrant = _bf(eng, Card(id='bear', name='Bear', type_line='Creature',
                               is_creature=True, power=2, toughness=2))
        eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD,
            instance_id=entrant.instance_id, controller_id='p1', object_types=['creature']))
        eng.resolve_until_stable()
        eng.resolve_pending_choice(answer)
    assert source.zone == Zone.BATTLEFIELD and source.counters == {'stun': 1}
    assert eng.state.player_by_id('p1').life == 21


@pytest.mark.parametrize('tail', [
    'Ignore a rule of your choice.',
    'You may put a dream counter on it. If you do not, draw a card.',
    "You may draw a card. If you don't, destroy target creature.",
])
def test_unrepresented_grant_bodies_remain_unclaimed(tail):
    card = Card(id='unsafe', name='Unsafe', type_line='Creature', is_creature=True, power=2, toughness=2,
        oracle_text='At the beginning of your upkeep, you may exile Unsafe. If you do, it gains '
                    f'"Whenever a land you control enters, if Unsafe is exiled, {tail}"')
    assert not parse_oracle(card).modeled


OMENKEEL = ('Whenever a Vehicle you control deals combat damage to a player, that player exiles '
    'that many cards from the top of their library. You may play lands from among those cards '
    'for as long as they remain exiled.\nCrew 1')


def _omenkeel(eng):
    card = card_from_scryfall_data({'id': 'cosima', 'name': 'Cosima // The Omenkeel',
        'layout': 'modal_dfc', 'keywords': ['Crew'], 'card_faces': [
            {'name': 'Cosima', 'mana_cost': '{2}{U}', 'type_line': 'Legendary Creature — God',
             'power': '2', 'toughness': '4', 'oracle_text': COSIMA},
            {'name': 'The Omenkeel', 'mana_cost': '{1}{U}', 'type_line': 'Legendary Artifact — Vehicle',
             'power': '3', 'toughness': '3', 'oracle_text': OMENKEEL},
        ]})
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    vehicle = _bf(eng, card.back_face())
    crew = _bf(eng, Card(id='crew', name='Crew', type_line='Creature',
                        is_creature=True, power=2, toughness=2))
    player = eng.state.player_by_id('p1')
    eng.activate_ability(player, vehicle, tap_choices=[crew.instance_id])
    eng.resolve_until_stable()
    assert vehicle.is_creature and (vehicle.power, vehicle.toughness) == (3, 3)
    return vehicle


def _library(eng, card):
    obj = GameObject(card, owner_id='p2', zone=Zone.LIBRARY)
    eng.state.player_by_id('p2').library.append(obj)
    return obj


def test_omenkeel_crews_and_grants_land_plays_including_a_modal_land_face():
    eng = _engine()
    vehicle = _omenkeel(eng)
    player = eng.state.player_by_id('p1')
    land = _library(eng, Card(id='land', name='Island', type_line='Basic Land — Island', is_land=True))
    spell = _library(eng, Card(id='spell', name='Spell', type_line='Instant', is_instant=True))
    modal = _library(eng, Card(id='modal', name='Spell front // Land back', type_line='Instant',
        is_instant=True, layout='modal_dfc', back_name='Land back', back_type_line='Land'))
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 3, source=vehicle, combat=True)
    eng.resolve_until_stable()
    assert all(obj.zone == Zone.EXILE for obj in (land, spell, modal))
    assert eng.can_play_land(player, land)
    assert eng.can_play_land(player, modal, face='back')
    assert not eng.can_cast(player, spell, assume_mana_available=True)
    assert not eng.can_cast(player, modal, assume_mana_available=True)
    eng._step_cleanup()
    assert all(obj.instance_id in eng.state.temp_play_permissions for obj in (land, spell, modal))
    clone = GameEngine(eng.state.clone())
    copied = clone.state.find_object(modal.instance_id)
    clone.play_land(clone.state.player_by_id('p1'), copied, face='back')
    assert copied.zone == Zone.BATTLEFIELD and copied.controller_id == 'p1' and copied.is_land
    assert modal.zone == Zone.EXILE
    eng.rules.return_to_hand(modal)
    eng.rules.exile(modal)
    assert not eng.can_play_land(player, modal, face='back')


def test_omenkeel_grant_remembers_ability_controller_across_source_control_change():
    eng = _engine()
    vehicle = _omenkeel(eng)
    land = _library(eng, Card(id='land', name='Forest', type_line='Basic Land — Forest', is_land=True))
    eng.rules.deal_damage(eng.state.player_by_id('p2'), 1, source=vehicle, combat=True)
    vehicle.controller_id = 'p2'
    eng.resolve_until_stable()
    assert land.zone == Zone.EXILE
    assert eng.state.temp_play_permission_player[land.instance_id] == 'p1'
