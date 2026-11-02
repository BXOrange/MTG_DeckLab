"""Skyblade's Boon keeps one activated ability available in exactly its printed zones."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = "Skyblade's Boon"


def test_registered_specs_are_fresh_and_bound():
    source = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(source.card), specs_for(source.card)
    assert [spec.ability_kind for spec in first] == ['static', 'activated', 'keyword']
    assert all(a is not b for a, b in zip(first, second))
    assert len(source.activated_abilities) == 1
    assert len(source.static_effects) == 2


@pytest.mark.parametrize('zone', [Zone.BATTLEFIELD, Zone.GRAVEYARD])
def test_one_ability_returns_aura_from_each_permitted_zone(zone):
    engine = _game()
    player = engine.state.players[0]
    target = battlefield_object(engine, player.id, 'Bear', 'Creature',
                                is_creature=True, power=2, toughness=2)
    source = _card(engine, NAME, zone=zone)
    if zone == Zone.BATTLEFIELD:
        source.attached_to = target.instance_id
    engine.recompute_continuous_effects()
    assert (target.power, target.toughness) == ((3, 3) if zone == Zone.BATTLEFIELD else (2, 2))
    assert ('flying' in target.granted_keywords) == (zone == Zone.BATTLEFIELD)
    player.mana_pool.add_many({'W': 1, 'C': 2})
    ability = source.activated_abilities[0]
    assert engine.can_activate(player, source, ability)
    assert any(action.get('type') == 'activate_ability' and action.get('instance_id') == source.instance_id
               for action in engine.legal_actions(player))
    engine.activate_ability(player, source)
    engine.resolve_until_stable()
    assert source in player.hand
    assert source not in player.graveyard and source not in engine.state.battlefield
    engine.recompute_continuous_effects()
    assert (target.power, target.toughness) == (2, 2)
    assert 'flying' not in target.granted_keywords


@pytest.mark.parametrize('zone', [Zone.HAND, Zone.EXILE, Zone.LIBRARY])
def test_activation_is_refused_outside_printed_zones(zone):
    engine = _game()
    player = engine.state.players[0]
    source = _card(engine, NAME, zone=zone)
    player.mana_pool.add_many({'W': 1, 'C': 2})
    assert not engine.can_activate(player, source, source.activated_abilities[0])


def test_opponent_cannot_activate_a_graveyard_card_they_do_not_own():
    engine = _game()
    player, opponent = engine.state.players
    source = _card(engine, NAME, zone=Zone.GRAVEYARD)
    opponent.mana_pool.add_many({'W': 1, 'C': 2})
    assert not engine.can_activate(opponent, source, source.activated_abilities[0])


@pytest.mark.parametrize('zones', [[], ['exile'], ['graveyard', 'unknown'], 'graveyard', [None], [{}]])
def test_activation_zone_vocabulary_fails_closed(zones):
    with pytest.raises(ValueError, match='activation zone'):
        parse_activation_cost({'activation_zones': zones})
