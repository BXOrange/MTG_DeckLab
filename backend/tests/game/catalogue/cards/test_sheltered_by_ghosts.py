"""Sheltered by Ghosts buffs its enchanted creature."""

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.binding.core import build_effects
from tests.support.catalogue import battlefield_object, two_player_game


def test_sheltered_by_ghosts_buffs_enchanted_creature():
    engine, player = two_player_game()
    bear = battlefield_object(
        engine, player.id, "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2,
    )
    aura = battlefield_object(engine, player.id, "Sheltered by Ghosts", "Enchantment — Aura")
    aura.attached_to = bear.instance_id
    specs = [effect for spec in _REGISTRY["sheltered by ghosts"]() if spec.ability_kind == "static" for effect in spec.effects]
    aura.static_effects.extend(build_effects(specs, aura))
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 2)
    assert "lifelink" in bear.granted_keywords
    assert bear.granted_ward_cost == "{2}"
