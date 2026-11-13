"""Eternal Flame counts controlled Mountains on resolution and rounds recoil up."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game, main_phase


def _board(count=3):
    engine = game()
    player = engine.state.player_by_id("p1")
    spell = card(engine, "Eternal Flame", zone=Zone.HAND)
    for index in range(count):
        filler(engine, f"Mountain {index}", type_line="Basic Land — Mountain")
    return engine, player, spell, engine.state.player_by_id("p2")


@pytest.mark.parametrize("count,recoil", [(0, 0), (1, 1), (3, 2), (4, 2)])
def test_counts_mountains_and_rounds_self_damage_up(count, recoil):
    engine, player, spell, opponent = _board(count)
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cast(engine, spell, targets=[opponent])
    assert opponent.life == 20 - count and player.life == 20 - recoil


def test_counts_nonbasic_and_stolen_mountains_but_not_opponents_mountains():
    engine, player, spell, opponent = _board(0)
    filler(engine, "Nonbasic", type_line="Land — Mountain")
    stolen = filler(engine, "Stolen", player="p2", type_line="Land — Mountain")
    stolen.controller_id = "p1"
    filler(engine, "Their Mountain", player="p2", type_line="Basic Land — Mountain")
    filler(engine, "Island", type_line="Basic Land — Island")
    cast(engine, spell, targets=[opponent])
    assert opponent.life == 18 and player.life == 19


def test_counts_on_resolution_instead_of_casting():
    engine, player, spell, opponent = _board(1)
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[opponent])
    filler(engine, "Later Mountain", type_line="Land — Mountain")
    engine.resolve_until_stable()
    assert opponent.life == 18 and player.life == 19


def test_cannot_target_caster_or_a_creature():
    engine, player, spell, opponent = _board()
    engine.state._physical_cast_validation = True
    creature = filler(engine, "Creature", player="p2", power=2, toughness=5)
    for target in (player, creature):
        with pytest.raises(ValueError):
            cast(engine, spell, targets=[target])
    assert player.life == opponent.life == 20


def test_can_target_a_planeswalker_you_control():
    engine, player, spell, opponent = _board()
    walker = card(engine, "Jace, the Mind Sculptor")
    walker.counters["loyalty"] = 3
    cast(engine, spell, targets=[walker])
    assert walker.zone == Zone.GRAVEYARD and player.life == 18 and opponent.life == 20
