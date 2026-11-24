"""Benthic Explorers couples an opposing land untap cost to that land's possible mana types."""
import pytest

from mtg_analyzer.game.card_registry.core import specs_for
from mtg_analyzer.game.mana_abilities import mana_abilities_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game


def board(land='Forest', player='p2'):
    engine = game(players=3, library=30)
    source = card(engine, 'Benthic Explorers')
    target = card(engine, land, player=player); target.tapped = True
    return engine, source, target


def ability(engine, source):
    engine.recompute_continuous_effects()
    result = mana_abilities_for(source, engine.state)
    assert len(result) == 1
    return result[0]


def activate(engine, source, land, color=None, choices=None):
    options = ability(engine, source).cost_land_options
    index = next(i for i, option in enumerate(options)
                 if option['instance_id'] == land.instance_id and (color is None or color in option['mana']))
    return engine.tap_for_mana(engine.state.players[0], source, option_index=index, tap_choices=choices)


def test_fresh_specs_and_one_native_mana_ability():
    engine, source, land = board(); a, b = specs_for(source.card), specs_for(source.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert ability(engine, source).cost.untap_others_scope == 'opponents'
    assert not source.activated_abilities


def test_actual_cast_and_immediate_mana_resolution():
    engine = game(library=30); source = card(engine, 'Benthic Explorers', zone=Zone.HAND)
    cast(engine, source); land = card(engine, 'Forest', player='p2'); land.tapped = True
    source.summoning_sick = False; player = engine.state.players[0]; player.mana_pool.empty()
    activate(engine, source, land)
    assert source.tapped and not land.tapped and player.mana_pool.to_dict()['G'] == 1
    assert not engine.state.stack


def test_cannot_pay_with_your_own_land():
    engine, source, land = board(player='p1')
    assert ability(engine, source).options == []
    with pytest.raises(ValueError):
        engine.tap_for_mana(engine.state.players[0], source, tap_choices=[land.instance_id])
    assert not source.tapped and land.tapped


def test_untapped_opposing_land_is_not_a_cost_candidate():
    engine, source, land = board(); land.tapped = False
    assert ability(engine, source).options == []
    with pytest.raises(ValueError):
        engine.tap_for_mana(engine.state.players[0], source)
    assert not source.tapped


def test_nonland_cannot_pay_untap_cost():
    engine, source, land = board('Sol Ring')
    assert ability(engine, source).options == []


def test_any_opponent_can_supply_the_land():
    engine, source, land = board(player='p3')
    activate(engine, source, land)
    assert not land.tapped and source.tapped


def test_colorless_is_a_possible_type():
    engine, source, land = board('Wastes')
    assert activate(engine, source, land, 'C') == {'C': 1}


def test_fixed_two_color_production_gives_a_choice_of_one_mana():
    engine, source, land = board('Azorius Chancery')
    assert {tuple(option) for option in ability(engine, source).options} == {('U',), ('W',)}
    assert activate(engine, source, land, 'U') == {'U': 1}


def test_hypothetical_land_ability_ignores_its_unpayable_mana_cost():
    engine, source, land = board('Shimmering Grotto')
    engine.state.players[1].mana_pool.empty()
    assert {color for option in ability(engine, source).options for color in option} == set('WUBRGC')
    assert activate(engine, source, land, 'R') == {'R': 1}


def test_does_not_take_a_type_from_a_different_land():
    engine, source, forest = board()
    island = card(engine, 'Island', player='p3'); island.tapped = True
    choices = ability(engine, source).cost_land_options
    green = next(i for i, option in enumerate(choices) if option['mana'] == {'G': 1})
    with pytest.raises(ValueError, match='does not match'):
        engine.tap_for_mana(engine.state.players[0], source, option_index=green, tap_choices=[island.instance_id])
    assert forest.tapped and island.tapped and not source.tapped


def test_selected_land_and_mana_are_bound_in_legal_action_options():
    engine, source, forest = board()
    island = card(engine, 'Island', player='p3'); island.tapped = True
    actions = [action for action in engine.legal_actions(engine.state.players[0])
               if action['type'] == 'tap_for_mana' and action['instance_id'] == source.instance_id]
    assert len(actions) == 1 and len(actions[0]['options']) == 2
    assert {option['cost_land_name'] for option in actions[0]['options']} == {'Forest', 'Island'}
    selected = next(option for option in actions[0]['options'] if option['mana'] == {'U': 1})
    engine.tap_for_mana(engine.state.players[0], source, option_index=selected['index'])
    assert not island.tapped and forest.tapped


def test_no_mana_land_can_be_untapped_and_produces_nothing():
    engine, source, land = board('Maze of Ith')
    assert ability(engine, source).options == [{}]
    assert activate(engine, source, land) == {}
    assert source.tapped and not land.tapped


def test_could_produce_includes_mana_type_replacement():
    engine, source, land = board('Azorius Chancery')
    card(engine, 'Damping Sphere')
    assert ability(engine, source).options == [{'C': 1}]
    assert activate(engine, source, land) == {'C': 1}


def test_reflecting_land_uses_real_producers_on_opponents_side():
    engine, source, land = board('Exotic Orchard')
    card(engine, 'Island')
    assert activate(engine, source, land) == {'U': 1}


def test_reflection_cycle_without_real_producer_has_no_type():
    engine, source, land = board('Exotic Orchard')
    card(engine, 'Exotic Orchard')
    assert ability(engine, source).options == [{}]
    assert activate(engine, source, land) == {}


def test_reflection_cycle_with_real_producer_reaches_that_type():
    engine, source, land = board('Exotic Orchard')
    card(engine, 'Exotic Orchard'); card(engine, 'Forest', player='p2')
    assert activate(engine, source, land) == {'G': 1}


def test_summoning_sickness_is_enforced_without_paying_other_cost():
    engine, source, land = board(); source.summoning_sick = True
    with pytest.raises(ValueError):
        activate(engine, source, land)
    assert land.tapped and not source.tapped


def test_tapped_source_cannot_activate_again():
    engine, source, land = board(); source.tapped = True
    with pytest.raises(ValueError):
        activate(engine, source, land)
    assert land.tapped


def test_copy_keeps_the_paid_land_and_does_not_untap_it_again():
    engine, source, land = board(); activate(engine, source, land)
    recipe = next(reversed(engine.state.copiable_stack_recipes.values()))
    engine.rules.copy_ability(recipe, 'p1', from_recipe=True)
    engine.resolve_until_stable()
    assert engine.state.players[0].mana_pool.to_dict()['G'] == 2 and not land.tapped


def test_copy_uses_last_known_land_after_departure():
    engine, source, land = board(); activate(engine, source, land)
    recipe = next(reversed(engine.state.copiable_stack_recipes.values()))
    engine.rules.exile(land)
    engine.rules.copy_ability(recipe, 'p1', from_recipe=True); engine.resolve_until_stable()
    assert engine.state.players[0].mana_pool.to_dict()['G'] == 2


def test_stale_land_visit_is_rejected_before_costs():
    engine, source, land = board()
    choice = ability(engine, source).cost_land_options[0]
    stale = [choice['instance_id'], choice['zone_incarnation']]
    engine.rules.put_into_graveyard(land); engine.rules.return_from_graveyard(land, 'battlefield')
    land.tapped = True
    with pytest.raises(ValueError, match='battlefield visit'):
        engine.tap_for_mana(engine.state.players[0], source, cost_land=stale)
    assert not source.tapped and land.tapped


def test_options_use_characteristics_after_untap_cost_without_mutating_live_land():
    from mtg_analyzer.game.effects.core import StaticAbility

    engine, source, land = board()
    grant = StaticAbility('ability', affects='self', source=land, params={'mana': [{'R': 1}]})
    grant.active_if = {'kind': 'source_untapped'}
    land.static_effects.append(grant)
    assert {color for option in ability(engine, source).options for color in option} == {'G', 'R'}
    assert land.tapped and not source.tapped
    assert activate(engine, source, land, 'R') == {'R': 1}


def test_session_dispatch_preserves_the_selected_land_visit():
    from mtg_analyzer.services.game_session import GameSession

    engine, source, land = board()
    session = GameSession(engine)
    offered = next(action for action in session.view('p1')['legal_actions']
                   if action['type'] == 'tap_for_mana' and action['instance_id'] == source.instance_id)
    selected = offered['options'][0]
    session.apply_action({'type': 'tap_for_mana', 'instance_id': source.instance_id,
                          'ability_index': offered['ability_index'], 'option_index': selected['index'],
                          'cost_land': selected['cost_land']})
    assert source.tapped and not land.tapped


def test_explorers_hypothetical_production_if_it_is_also_a_land():
    from mtg_analyzer.game.effects.core import StaticAbility
    from mtg_analyzer.game.mana_abilities import mana_types_a_land_could_produce

    engine, source, land = board()
    source.static_effects.append(StaticAbility('type', affects='self', source=source,
                                               params={'add_types': ['land']}))
    engine.recompute_continuous_effects()
    assert source.is_land
    assert mana_types_a_land_could_produce(source, engine.state) == {'G'}
