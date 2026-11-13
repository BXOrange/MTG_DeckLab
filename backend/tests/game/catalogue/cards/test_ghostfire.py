"""Ghostfire is colorless while still requiring red mana to cast."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.cards.card_colors import effective_colors
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, game, main_phase


def test_deals_three_to_player_as_colorless_damage():
    engine = game()
    spell = card(engine, "Ghostfire", zone=Zone.HAND)
    player = engine.state.player_by_id("p2")
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    assert not effective_colors(spell) and spell.card.color_identity == {"R"}
    cast(engine, spell, targets=[player])
    assert player.life == 17 and spell.zone == Zone.GRAVEYARD
    assert not effective_colors(spell)
    hit = next(event for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE)
    assert not hit.get("source_colors")


def test_can_target_and_kill_a_creature_with_protection_from_red():
    engine = game()
    spell = card(engine, "Ghostfire", zone=Zone.HAND)
    victim = card(engine, "Kor Firewalker", player="p2")
    cast(engine, spell, targets=[victim])
    assert victim.zone == Zone.GRAVEYARD
    # Ghostfire is not a red spell, so Firewalker's red-cast life trigger does not fire.
    assert engine.state.player_by_id("p2").life == 20


def test_cast_requires_red_mana_and_spell_is_colorless_on_stack():
    engine = game()
    spell = card(engine, "Ghostfire", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    target = engine.state.player_by_id("p2")
    main_phase(engine)
    player.mana_pool.add("C", 3)
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=[target])
    player.mana_pool.add("R", 1)
    engine.cast_spell(player, spell, targets=[target])
    assert spell.zone == Zone.STACK and not effective_colors(spell)
    engine.resolve_until_stable()
    assert target.life == 17
