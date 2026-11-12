"""Sonar Strike's three-state target restriction and Bat-dependent life gain."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game, main_phase


def _board():
    engine = game()
    spell = card(engine, "Sonar Strike", zone=Zone.HAND)
    target = filler(engine, "Target", player="p2", power=2, toughness=6)
    return engine, engine.state.player_by_id("p1"), spell, target


@pytest.mark.parametrize("state", ["attacking", "blocking", "tapped"])
def test_each_target_state_is_sufficient_and_deals_four(state):
    engine, player, spell, target = _board()
    if state == "blocking":
        target.blocking = filler(engine, "Attacker", power=2, toughness=6).instance_id
    else:
        setattr(target, state, True)
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cast(engine, spell, targets=[target])
    assert target.damage_marked == 4 and player.life == 20


def test_idle_untapped_creature_is_not_a_legal_target():
    engine, player, spell, target = _board()
    with pytest.raises(ValueError):
        cast(engine, spell, targets=[target])
    assert spell in player.hand and target.damage_marked == 0


@pytest.mark.parametrize("bat_controller,life", [("p1", 23), ("p2", 20)])
def test_only_a_bat_you_control_grants_life(bat_controller, life):
    engine, player, spell, target = _board()
    target.tapped = True
    filler(engine, "Bat", type_line="Creature — Bat", player=bat_controller, power=1, toughness=1)
    cast(engine, spell, targets=[target])
    assert target.damage_marked == 4 and player.life == life


def test_lethally_damaged_bat_still_counts_until_spell_finishes():
    engine, player, spell, target = _board()
    bat = filler(engine, "Bat", type_line="Creature — Bat", power=1, toughness=1)
    bat.tapped = True
    cast(engine, spell, targets=[bat])
    assert bat.zone == Zone.GRAVEYARD and player.life == 23


def test_target_becoming_illegal_stops_damage_and_life_gain():
    engine, player, spell, target = _board()
    filler(engine, "Bat", type_line="Creature — Bat", power=1, toughness=1)
    target.tapped = True
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[target])
    target.tapped = False
    engine.resolve_until_stable()
    assert target.damage_marked == 0 and player.life == 20


def test_bat_condition_is_checked_on_resolution():
    engine, player, spell, target = _board()
    target.tapped = True
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[target])
    filler(engine, "Bat", type_line="Creature — Bat", power=1, toughness=1)
    engine.resolve_until_stable()
    assert player.life == 23
