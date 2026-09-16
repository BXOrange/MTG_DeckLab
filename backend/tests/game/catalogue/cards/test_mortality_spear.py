"""Mortality Spear discounts itself after its controller gains life."""

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.continuous import self_cost_reduction_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import two_player_game


def test_mortality_spear_discount_only_after_lifegain():
    engine, player = two_player_game()
    spear = GameObject(Card(id="ms", name="Mortality Spear", type_line="Instant"), owner_id=player.id, zone=Zone.HAND)
    spear.controller_id = player.id
    specs = [effect for spec in _REGISTRY["mortality spear"]() if spec.ability_kind == "static" for effect in spec.effects]
    spear.static_effects.extend(build_effects(specs, spear))
    assert self_cost_reduction_for(spear, engine.state, player.id)[0] == 0
    engine.rules.gain_life(player, 1)
    assert self_cost_reduction_for(spear, engine.state, player.id)[0] == 2
