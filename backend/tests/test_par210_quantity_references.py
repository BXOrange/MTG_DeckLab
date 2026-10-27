"""PAR-210: quantities bind to the activation snapshot or its explicit turn-history antecedent."""
from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.game import creature
from tests.test_par210_player_references import DB, board, game


@pytest.mark.parametrize('name', ['Relic Amulet', 'Geistflame Reservoir', 'Sawblade Skinripper'])
def test_named_quantity_cards_are_fully_modeled(name):
    assert parse_oracle(DB.get_card(name)).modeled


def test_relic_amulet_damage_is_the_number_removed_not_the_remaining_counters():
    eng = game()
    source = board(eng, DB.get_card('Relic Amulet'))
    victim = board(eng, creature('Victim', toughness=12), 'p2')
    source.counters['charge'] = 3
    eng.state.player_by_id('p1').mana_pool.add('C', 2)
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[victim])
    source.counters['charge'] = 9
    eng.resolve_until_stable()
    assert victim.damage_marked == 3


@pytest.mark.parametrize('clone', [False, True])
def test_each_activation_keeps_its_own_counter_payment_after_clone_and_source_departure(clone):
    eng = game()
    card = Card(id='counter-source', name='Counter Source', type_line='Artifact',
                oracle_text='Remove any number of charge counters from ~: ~ deals that much damage to any target.')
    assert parse_oracle(card).modeled
    source = board(eng, card)
    source.counters['charge'] = 7
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    eng.activate_ability(p1, source, targets=[p2], x=2)
    eng.activate_ability(p1, source, targets=[p2], x=3)
    eng.rules.destroy(source)
    if clone:
        eng = GameEngine(eng.state.clone())
    eng.resolve_until_stable()
    assert eng.state.player_by_id('p2').life == 15


def test_geistflame_uses_the_announced_counter_quantity():
    eng = game()
    source = board(eng, DB.get_card('Geistflame Reservoir'))
    source.counters['charge'] = 5
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    p1.mana_pool.add_many({'R': 1, 'C': 1})
    eng.activate_ability(p1, source, targets=[p2], x=2)
    eng.resolve_until_stable()
    assert p2.life == 18 and source.counters['charge'] == 3


def test_sawblade_counts_its_controllers_sacrifices_again_at_resolution():
    eng = game()
    saw = board(eng, DB.get_card('Sawblade Skinripper'))
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    for i in range(2):
        board(eng, creature(f'Victim {i}'))
        eng.rules.sacrifice(p1, 'creature', exclude=saw)
    board(eng, creature('Opponent victim'), 'p2')
    eng.rules.sacrifice(p2, 'creature')
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1', controller_id='p1'))
    eng.rules.put_triggers_on_stack()
    if eng.state.pending_choice:
        choice = eng.state.pending_choice
        option = next(o['id'] for o in choice['options'] if o['id'] in ('p2', 'player:p2'))
        eng.rules.resolve_choice(option)
    board(eng, creature('Late victim'))
    eng.rules.sacrifice(p1, 'creature', exclude=saw)
    eng.resolve_until_stable()
    assert p2.life == 17
    assert len(p1.graveyard) == 3


@pytest.mark.parametrize('text', [
    '~ deals that much damage to any target.',
    '{2}, {T}: ~ deals that much damage to any target.',
    'At the beginning of your end step, if you control two creatures, ~ deals that much damage to any target.',
])
def test_unbound_quantity_is_not_claimed(text):
    assert not parse_oracle(creature('Unbound', oracle_text=text)).modeled


def test_history_quantity_uses_the_ability_controller_after_source_control_changes():
    from mtg_analyzer.game.effect_amounts import amount_of
    eng = game()
    saw = board(eng, DB.get_card('Sawblade Skinripper'))
    p1 = eng.state.player_by_id('p1')
    for i in range(2):
        board(eng, creature(f'Victim {i}'))
        eng.rules.sacrifice(p1, 'creature', exclude=saw)
    amount = next(e.params['amount'] for s in parse_oracle(saw.card).specs for e in s.effects
                  if e.type == 'damage')
    saw.controller_id = 'p2'
    eng.rules.context.resolving_controller_id = 'p1'
    assert amount_of(amount, eng.rules.context, saw, None) == 2
