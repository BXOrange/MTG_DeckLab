"""Kitsune Bonesetter enforces the hand comparison at activation, then prevents damage."""
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game
from tests.support.catalogue import battlefield_object

NAME = 'Kitsune Bonesetter'


def test_registered_specs_are_fresh_and_bound():
    source = _card(_game(), NAME)
    first, second = specs_for(source.card), specs_for(source.card)
    assert [spec.ability_kind for spec in first] == ['activated']
    assert first[0] is not second[0]
    assert first[0].effects[0].params is not second[0].effects[0].params
    assert len(source.activated_abilities) == 1


def test_hand_size_must_be_strictly_greater_than_every_opponent():
    engine = _game(3)
    player, first, second = engine.state.players
    source = _card(engine, NAME)
    source.summoning_sick = False
    ability = source.activated_abilities[0]
    assert not engine.can_activate(player, source, ability)  # zero cards ties
    _card(engine, 'Forest', zone=Zone.HAND)
    assert engine.can_activate(player, source, ability)
    _card(engine, 'Forest', second.id, Zone.HAND)
    assert not engine.can_activate(player, source, ability)  # third player's tie
    _card(engine, 'Forest', zone=Zone.HAND)
    assert engine.can_activate(player, source, ability)
    for _ in range(3):
        _card(engine, 'Forest', first.id, Zone.HAND)
    assert not engine.can_activate(player, source, ability)


def test_prevention_resolves_even_if_hand_comparison_later_stops_holding():
    engine = _game()
    player, opponent = engine.state.players
    source = _card(engine, NAME)
    source.summoning_sick = False
    _card(engine, 'Forest', zone=Zone.HAND)
    target = battlefield_object(engine, player.id, 'Large creature', 'Creature',
                                is_creature=True, power=10, toughness=10)
    engine.activate_ability(player, source, targets=[target])
    _card(engine, 'Forest', opponent.id, Zone.HAND)  # restriction is activation-only
    engine.resolve_until_stable()
    assert source.tapped
    engine.rules.deal_damage(target, 5)
    assert target.damage_marked == 2
    engine.rules.deal_damage(target, 2)
    assert target.damage_marked == 4
