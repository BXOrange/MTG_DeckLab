"""Darksteel Mutation neutralizes its enchanted creature."""

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.binding.core import build_effects
from tests.support.catalogue import battlefield_object, two_player_game


def test_darksteel_mutation_neuters_enchanted_creature():
    engine, player = two_player_game()
    dragon = battlefield_object(
        engine, player.id, "Big Dragon", "Creature — Dragon", is_creature=True, power=6, toughness=6,
    )
    aura = battlefield_object(engine, player.id, "Darksteel Mutation", "Enchantment — Aura")
    aura.attached_to = dragon.instance_id
    specs = [effect for spec in _REGISTRY["darksteel mutation"]() if spec.ability_kind == "static" for effect in spec.effects]
    aura.static_effects.extend(build_effects(specs, aura))
    engine.recompute_continuous_effects()
    assert (dragon.power, dragon.toughness) == (0, 1)
    assert dragon.loses_all_abilities
    assert "indestructible" in dragon.granted_keywords
