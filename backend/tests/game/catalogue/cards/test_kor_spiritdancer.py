"""Kor Spiritdancer scales with Auras attached to it."""

from mtg_analyzer.game.card_registry import _REGISTRY
from mtg_analyzer.game.binding.core import build_effects
from tests.support.catalogue import battlefield_object, two_player_game


def test_kor_spiritdancer_scales_with_attached_auras():
    engine, player = two_player_game()
    kor = battlefield_object(
        engine, player.id, "Kor Spiritdancer", "Creature — Kor Wizard",
        is_creature=True, power=0, toughness=2,
    )
    specs = [spec.effects[0] for spec in _REGISTRY["kor spiritdancer"]() if spec.ability_kind == "static"]
    kor.static_effects.extend(build_effects(specs, kor))
    engine.recompute_continuous_effects()
    assert (kor.power, kor.toughness) == (0, 2)

    for index in range(2):
        aura = battlefield_object(engine, player.id, f"Aura{index}", "Enchantment — Aura")
        aura.attached_to = kor.instance_id
    engine.recompute_continuous_effects()
    assert (kor.power, kor.toughness) == (4, 6)
