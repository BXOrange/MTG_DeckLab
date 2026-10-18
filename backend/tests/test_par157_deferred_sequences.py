"""Delay a whole composed blink while retaining its original source visit."""
import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.flicker_sequences import flicker_sequence_specs
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


def _attacking_galleon():
    eng = _engine()
    card = _cached("Conqueror's Galleon // Conqueror's Foothold")
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card, 'p2')
    source.controller_id = 'p1'
    helper = _bf(eng, _creature('Crew', power=4, toughness=4))
    player = eng.state.player_by_id('p1')
    eng.activate_ability(player, source, 0, tap_choices=[helper.instance_id])
    eng.resolve_until_stable()
    eng.state.current_step = 'declare_attackers'
    eng.declare_attackers(player, [source])
    return eng, source


def _revisit(eng, source):
    eng.rules.exile(source)
    eng.rules.return_from_exile(source, source.zone_incarnation)


@pytest.mark.full_cache
def test_galleon_delays_both_actions_and_returns_a_working_back_under_original_controller():
    eng, source = _attacking_galleon()
    incarnation = source.zone_incarnation
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and not source.transformed
    assert len(eng.state.delayed_triggers) == 1
    source.controller_id = 'p2'
    eng._fire_delayed_triggers('end_combat')
    assert source.zone == Zone.BATTLEFIELD
    clone = GameEngine(eng.state.clone())
    clone.resolve_until_stable()
    returned = clone.state.find_object(source.instance_id)
    assert returned.zone == Zone.BATTLEFIELD and returned.transformed
    assert returned.name == "Conqueror's Foothold" and returned.is_land and not returned.is_creature
    assert returned.zone_incarnation > incarnation
    assert returned.controller_id == 'p1' and returned.owner_id == 'p2'
    player = clone.state.player_by_id('p1')
    before = player.mana_pool.total()
    clone.tap_for_mana(player, returned)
    clone.resolve_until_stable()
    assert player.mana_pool.total() == before + 1
    assert source.zone == Zone.BATTLEFIELD and not source.transformed


@pytest.mark.full_cache
@pytest.mark.parametrize('when', ['before_arm', 'after_arm', 'on_stack'])
def test_galleon_delayed_blink_cannot_follow_a_later_battlefield_visit(when):
    eng, source = _attacking_galleon()
    if when == 'before_arm':
        _revisit(eng, source)
    eng.resolve_until_stable()
    if when == 'after_arm':
        _revisit(eng, source)
    eng._fire_delayed_triggers('end_combat')
    if when == 'on_stack':
        _revisit(eng, source)
    incarnation = source.zone_incarnation
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and not source.transformed
    assert source.zone_incarnation == incarnation


@pytest.mark.parametrize('when,step', [
    ('at end of combat', 'end_combat'),
    ('at the beginning of your next upkeep', 'upkeep'),
    ('at the beginning of the next end step', 'end'),
])
def test_unregistered_source_composes_deferred_exile_timing_with_entry_and_return_timing(when, step):
    eng = _engine()
    source = _bf(eng, Card(id='front', name='Front', type_line='Creature', is_creature=True,
        power=2, toughness=3, layout='transform', back_name='Back',
        back_type_line='Creature', back_power=4, back_toughness=5, back_oracle_text='Flying'))
    specs = parse_effect_body(f'exile ~ {when}, then return it to the battlefield transformed '
        'tapped with a dream counter on it at the beginning of your next end step')
    assert specs and specs[0].type == 'create_delayed_trigger'
    for effect in build_effects(specs, source):
        effect.apply(eng.rules.context)
    assert source.zone == Zone.BATTLEFIELD
    eng._fire_delayed_triggers(step)
    eng.resolve_until_stable()
    assert source.zone == Zone.EXILE
    eng._fire_delayed_triggers('end')
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.transformed and source.tapped
    assert source.counters.get('dream') == 1


@pytest.mark.full_cache
def test_delayed_source_keeps_reference_after_an_in_place_characteristic_change():
    eng, source = _attacking_galleon()
    eng.resolve_until_stable()
    eng.rules.transform_permanent(source)
    incarnation = source.zone_incarnation
    eng._fire_delayed_triggers('end_combat')
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.transformed
    assert source.zone_incarnation > incarnation


@pytest.mark.parametrize('body', [
    'exile it at end of combat, then return it to the battlefield',
    'exile ~ at the end of an imaginary step, then return it to the battlefield',
    'exile target creature at end of combat, then return it to the battlefield',
])
def test_deferred_source_parser_does_not_invent_subjects_timing_or_targets(body):
    assert flicker_sequence_specs(body) is None


@pytest.mark.full_cache
def test_pending_crew_grant_cannot_animate_a_new_visit_of_its_vehicle():
    eng = _engine()
    source = _bf(eng, _cached("Conqueror's Galleon // Conqueror's Foothold"))
    helper = _bf(eng, _creature('Crew', power=4, toughness=4))
    eng.activate_ability(eng.state.player_by_id('p1'), source, 0, tap_choices=[helper.instance_id])
    _revisit(eng, source)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert source.zone == Zone.BATTLEFIELD and not source.is_creature
