"""Thrull Parasite: mandatory removal, controller choice, costs and Extort."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

ORACLE = ('Extort (Whenever you cast a spell, you may pay {W/B}. If you do, each '
          'opponent loses 1 life and you gain that much life.)\n'
          '{T}, Pay 2 life: Remove a counter from target nonland permanent.')


def setup(counters=None, land=False):
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    card = Card(id='parasite', name='Thrull Parasite', type_line='Creature — Thrull',
                is_creature=True, power=1, toughness=1, oracle_text=ORACLE, keywords=['Extort'])
    source = GameObject(card, owner_id='p1', zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    target = GameObject(Card(id='target', name='Target', type_line='Land' if land else 'Artifact',
                             is_land=land), owner_id='p2', zone=Zone.BATTLEFIELD)
    target.counters.update(counters or {})
    eng.state.add_to_battlefield(target)
    eng.recompute_continuous_effects()
    return eng, source, target


def test_registered_fresh_and_bound():
    eng, source, target = setup()
    first, second = specs_for(source.card), specs_for(source.card)
    assert first[0] is not second[0]
    assert first[0].effects[0] is not second[0].effects[0]
    assert len(source.activated_abilities) == 1
    assert source.triggered_abilities  # Extort survives catalogue registration.


@pytest.mark.parametrize('counters', [{}, {'charge': 3}, {'charge': 2, 'shield': 1}])
def test_remove_exactly_one_with_cost_and_activators_choice(counters):
    eng, source, target = setup(counters)
    player = eng.state.player_by_id('p1')
    before = player.life
    eng.activate_ability(player, source, targets=[target])
    assert source.tapped and player.life == before - 2
    assert target.counters == counters
    eng.rules.resolve_top_of_stack()
    if len(counters) > 1:
        choice = eng.state.pending_choice
        assert choice['kind'] == 'remove_counters_kind'
        assert choice['player_id'] == 'p1'
        eng.resolve_pending_choice('shield')
        assert target.counters.get('shield', 0) == 0
        assert target.counters['charge'] == 2
    else:
        assert eng.state.pending_choice is None
        assert target.counters.get('charge', 0) == max(0, counters.get('charge', 0) - 1)


def test_land_cannot_be_targeted_and_no_cost_is_paid():
    eng, source, target = setup({'charge': 1}, land=True)
    player = eng.state.player_by_id('p1')
    before = player.life
    with pytest.raises(ValueError):
        eng.activate_ability(player, source, targets=[target])
    assert player.life == before and not source.tapped


def test_extort_still_drains_on_cast():
    eng, source, target = setup()
    player = eng.state.player_by_id('p1')
    spell = GameObject(Card(id='spell', name='Spell', type_line='Instant', is_instant=True),
                       owner_id='p1', zone=Zone.HAND)
    player.add_to_zone(spell, Zone.HAND)
    player.mana_pool.add('W', 1)
    before = player.life
    opponent = eng.state.player_by_id('p2')
    other_before = opponent.life
    eng.rules.cast_spell(player, spell)
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice['kind'] == 'pay_cost_then'
    eng.rules.resolve_choice('pay')
    assert player.life == before + 1
    assert opponent.life == other_before - 1


@pytest.mark.parametrize('text,expected', [
    ('remove a counter from target permanent', {'target_kind': 'permanent', 'exact_count': 1}),
    ('remove 2 counters from target creature', {'target_kind': 'creature', 'exact_count': 2}),
    ('remove a charge counter from target permanent', {'target_kind': 'permanent', 'kind': 'charge', 'count': 1}),
])
def test_shared_counter_grammar(text, expected):
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    specs = match_clause(text)
    assert specs and specs[0].type == 'remove_counters'
    assert specs[0].params == expected


@pytest.mark.parametrize('text', [
    'remove a counter from target permanent unless its controller pays {1}',
    'remove a counter from target permanent and draw a card',
    'remove a counter from target spell',
])
def test_unsupported_counter_variants_fail_closed(text):
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    assert match_clause(text) is None


def test_multiple_counter_choices_keep_resolving_player():
    from mtg_analyzer.game.effects.registry import EffectRegistry
    from mtg_analyzer.game.effects.core import GameContext
    eng, source, target = setup({'charge': 2, 'shield': 2})
    effect = EffectRegistry.create('remove_counters', {'target_kind': 'permanent', 'exact_count': 2})
    effect.source = source
    effect.apply(GameContext(eng.state, eng.rules), [target])
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('shield')
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('charge')
    assert target.counters == {'charge': 1, 'shield': 1}


def test_ability_controller_keeps_choice_after_source_changes_control():
    eng, source, target = setup({'charge': 2, 'shield': 1})
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[target])
    source.controller_id = 'p2'
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice['player_id'] == 'p1'
    eng.resolve_pending_choice('charge')
    assert target.counters == {'charge': 1, 'shield': 1}


def test_cannot_pay_two_life_when_only_one_remains():
    eng, source, target = setup({'charge': 2})
    player = eng.state.player_by_id('p1')
    player.life = 1
    with pytest.raises(ValueError):
        eng.activate_ability(player, source, targets=[target])
    assert player.life == 1 and not source.tapped


def test_spinal_parasite_pays_two_counters_and_removes_one():
    eng, old_source, target = setup({'charge': 3})
    source = GameObject(Card(
        id='spinal', name='Spinal Parasite', type_line='Artifact Creature — Insect',
        is_creature=True, power=0, toughness=0,
        oracle_text='Sunburst\nRemove two +1/+1 counters from this creature: Remove a counter from target permanent.',
    ), owner_id='p1', zone=Zone.BATTLEFIELD)
    source.counters['+1/+1'] = 3
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    eng.recompute_continuous_effects()
    eng.activate_ability(eng.state.player_by_id('p1'), source, targets=[target])
    assert source.counters['+1/+1'] == 1
    eng.rules.resolve_top_of_stack()
    assert target.counters['charge'] == 2


def test_medicine_runner_etb_offers_optional_target_and_removes_one():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    eng, _, target = setup({'charge': 3})
    source = GameObject(Card(
        id='medicine', name='Medicine Runner', type_line='Creature — Elf Cleric',
        is_creature=True, power=2, toughness=1,
        oracle_text='When this creature enters, you may remove a counter from target permanent.',
    ), owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(source)
    eng.state.add_to_battlefield(source)
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=source.instance_id,
                                   player_id='p1'))
    eng.rules.put_triggers_on_stack()
    choice = eng.state.pending_choice
    assert choice['kind'] == 'trigger_target'
    assert any(option['id'] == 'decline' for option in choice['options'])
    selected = next(option['id'] for option in choice['options']
                    if str(target.instance_id) == str(option['id']))
    eng.resolve_pending_choice(str(selected))
    eng.rules.resolve_top_of_stack()
    assert target.counters['charge'] == 2


def test_unnamed_self_removal_composes_with_existing_referent_wrapper():
    eng, source, _ = setup()
    source.card = Card(id='self-removal', name='Self Remover', type_line='Artifact',
                       oracle_text='{0}: Remove a counter from this artifact.')
    source.activated_abilities.clear()
    source.triggered_abilities.clear()
    source.counters.update({'charge': 2, 'shield': 1})
    bind_from_catalogue(source)
    eng.activate_ability(eng.state.player_by_id('p1'), source)
    eng.rules.resolve_top_of_stack()
    assert eng.state.pending_choice['kind'] == 'remove_counters_kind'
    eng.resolve_pending_choice('charge')
    assert source.counters == {'charge': 1, 'shield': 1}
