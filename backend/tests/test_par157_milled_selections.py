"""Captured mill pools and locked temporary grants compose across faces."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _engine, _bf, _creature
from test_par157_back_selections import _cached


def _library(eng, name, oracle=''):
    card = _creature(name, oracle_text=oracle)
    obj = GameObject(card, owner_id='p1', zone=Zone.LIBRARY)
    bind_from_catalogue(obj)
    eng.state.player_by_id('p1').library.append(obj)
    return obj


def _apply(eng, source, text):
    specs = parse_effect_body(text)
    assert specs
    eng.rules._apply_effect_specs([spec.to_dict() for spec in specs], source)


def _pick(eng, obj):
    assert eng.state.pending_choice['kind'] == 'choose_objects'
    eng.resolve_pending_choice(str(obj.instance_id))


def test_mill_pool_is_local_and_all_selected_cards_enter_together_after_selection():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    watchers = [_library(eng, f'Watcher{i}', 'Whenever another creature enters, you gain 1 life.') for i in range(3)]
    old = GameObject(_creature('Old graveyard card'), owner_id='p1', zone=Zone.GRAVEYARD)
    eng.state.player_by_id('p1').graveyard.append(old)
    eng.state.active_player_index = 1  # "you mill" still refers to p1.
    _apply(eng, source, 'mill 10 cards. put up to 2 creature cards from among the milled cards onto the battlefield')
    offered = {o['id'] for o in eng.state.pending_choice['options']}
    assert offered == {str(o.instance_id) for o in watchers} | {'decline'}
    assert len(eng.state.player_by_id('p2').library) == 5
    _pick(eng, watchers[0])
    assert all(o.zone == Zone.GRAVEYARD for o in watchers)
    clone = GameEngine(eng.state.clone())
    _pick(eng, watchers[1])
    _pick(clone, watchers[2])
    assert watchers[0].zone == watchers[1].zone == Zone.BATTLEFIELD
    assert watchers[2].zone == Zone.GRAVEYARD
    assert clone.state.find_object(watchers[1].instance_id).zone == Zone.GRAVEYARD
    assert clone.state.find_object(watchers[2].instance_id).zone == Zone.BATTLEFIELD
    assert eng.state.player_by_id('p1').life == 22  # both see the other entrant
    assert old.zone == Zone.GRAVEYARD


@pytest.mark.parametrize('tail', ['with an imaginary ability', 'under an opponent control'])
def test_unsupported_mill_recovery_qualifiers_fail_closed(tail):
    assert not parse_effect_body('put up to 2 creature cards from among the milled cards onto the battlefield ' + tail)


def test_partial_mill_selection_can_finish_and_does_not_return_a_later_visit():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    first, second = [_library(eng, name) for name in ['First', 'Second']]
    _apply(eng, source, 'mill 10 cards. put up to 2 creature cards from among the milled cards onto the battlefield')
    _pick(eng, first)
    eng.rules.exile(first)
    player = eng.state.player_by_id('p1')
    player.exile.remove(first)
    player.add_to_zone(first, Zone.GRAVEYARD)
    _pick(eng, second)
    assert first.zone == Zone.GRAVEYARD and second.zone == Zone.BATTLEFIELD


def test_finishing_after_one_mill_pick_returns_only_that_card():
    eng = _engine()
    source = _bf(eng, _creature('Source'))
    first, second = [_library(eng, name) for name in ['First', 'Second']]
    _apply(eng, source, 'mill 10 cards. put up to 2 creature cards from among the milled cards onto the battlefield')
    _pick(eng, first)
    eng.resolve_pending_choice('decline')
    assert first.zone == Zone.BATTLEFIELD and second.zone == Zone.GRAVEYARD


@pytest.mark.full_cache
def test_vorinclex_activates_front_recovers_milled_cards_and_grants_fight_before_returning():
    eng = _engine()
    card = _cached('Vorinclex // The Grand Evolution')
    assert parse_oracle(card).modeled and parse_oracle(card.back_face()).modeled
    source = _bf(eng, card)
    creatures = [_library(eng, f'Milled{i}') for i in range(2)]
    player = eng.state.player_by_id('p1')
    player.mana_pool.add_many({'C': 6, 'G': 2})
    eng.activate_ability(player, source, 0)
    eng.resolve_until_stable()
    assert source.transformed and source.name == card.back_name
    _pick(eng, creatures[0])
    _pick(eng, creatures[1])
    # Chapter II already uses the shared distributed-counter effect;
    # isolate the newly supported last chapter at its next lore event.
    source.counters['lore'] = 2
    eng.rules.advance_sagas(player)
    eng.resolve_until_stable()
    assert not source.transformed and source.name == card.name
    assert len(source.activated_abilities) == 1  # the new front has no old fight grant
    assert all(len(o.granted_activated_abilities) == 1 for o in creatures)
    later = _bf(eng, _creature('Later'))
    assert not later.granted_activated_abilities
    enemy = _bf(eng, _creature('Enemy', 1, 1), 'p2')
    player.mana_pool.add('C', 1)
    eng.activate_ability(player, creatures[0], 0, [enemy])
    eng.resolve_until_stable()
    assert enemy.zone == Zone.GRAVEYARD and creatures[0].damage_marked == 1
    eng.rules.blink(creatures[1])
    assert not creatures[1].granted_activated_abilities
    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert not creatures[0].granted_activated_abilities


def test_quoted_inner_connectors_and_periods_remain_inside_the_granted_ability():
    text = ('until end of turn, creatures you control gain "{1}: you gain 1 life and draw 1 card." '
            'you gain 2 life')
    specs = parse_effect_body(text)
    assert specs and [s.type for s in specs] == ['grant_until', 'gain_life']
    inner = specs[0].params['static']['params']['grant_effects']
    assert [s['type'] for s in inner] == ['gain_life', 'draw']
