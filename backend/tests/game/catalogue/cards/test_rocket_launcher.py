"""Rocket Launcher (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Rocket Launcher'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


def _next_own_upkeep(engine):
    turn = engine.state.internal_turn.number
    for _ in range(50):
        engine.advance_step()
        engine.resolve_until_stable()
        if (engine.state.current_step == "upkeep" and engine.state.active_player.id == "p1"
                and engine.state.internal_turn.number > turn): return
    raise AssertionError("No next own upkeep")


def test_end_to_end():
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _end_step
    engine = _game()
    player, opponent = engine.state.players
    launcher = _card(engine, NAME)
    player.mana_pool.add("C", 2)
    assert not engine.can_activate(player, launcher, launcher.activated_abilities[0])
    launcher.temp_keywords.add("haste")
    engine.recompute_continuous_effects()
    assert not engine.can_activate(player, launcher, launcher.activated_abilities[0])
    _next_own_upkeep(engine)
    player.mana_pool.add("C", 4)
    assert engine.can_activate(player, launcher, launcher.activated_abilities[0])
    for _ in range(2):
        engine.activate_ability(player, launcher, targets=[opponent])
        engine.resolve_until_stable()
    assert opponent.life == 18 and launcher.zone == Zone.BATTLEFIELD
    _end_step(engine)
    engine.resolve_until_stable()
    assert launcher.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("bounce_before_resolution", [False, True])
def test_delayed_destruction_does_not_follow_a_new_battlefield_visit(bounce_before_resolution):
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _end_step
    engine = _game()
    player, opponent = engine.state.players
    launcher = _card(engine, NAME)
    launcher.summoning_sick = False
    player.mana_pool.add("C", 2)
    engine.activate_ability(player, launcher, targets=[opponent])
    if not bounce_before_resolution:
        engine.resolve_until_stable()
    engine.rules.return_to_hand(launcher)
    engine.rules.cast_without_paying(player, launcher)
    engine.resolve_until_stable()
    assert opponent.life == 19
    assert launcher.zone == Zone.BATTLEFIELD
    _end_step(engine)
    engine.resolve_until_stable()
    assert launcher.zone == Zone.BATTLEFIELD


def test_control_changes_reset_the_restriction_even_if_control_returns():
    from mtg_analyzer.game.control import gain_control
    engine = _game()
    player, opponent = engine.state.players
    launcher = _card(engine, NAME)
    launcher.summoning_sick = False
    player.mana_pool.add("C", 2)
    assert engine.can_activate(player, launcher, launcher.activated_abilities[0])
    gain_control(engine.state, launcher, "p2")
    gain_control(engine.state, launcher, "p1")
    engine.recompute_continuous_effects()
    assert not engine.can_activate(player, launcher, launcher.activated_abilities[0])


@pytest.mark.parametrize("phased", [False, True])
def test_skipped_untap_does_not_delay_continuous_control_eligibility(phased):
    from mtg_analyzer.game.effects.core import StaticEffect
    engine = _game()
    player = engine.state.players[0]
    launcher = _card(engine, NAME)
    launcher.tapped = True
    launcher.phased_out = phased
    player.player_effects.append(StaticEffect("skip_phase", {"phase": "untap"}, duration="permanent"))
    _next_own_upkeep(engine)
    assert launcher.tapped  # the untap instruction really was skipped
    assert not launcher.summoning_sick
    # It may act once present again; phase-out itself does not break continuous control.
    launcher.phased_out = False
    player.mana_pool.add("C", 2)
    assert engine.can_activate(player, launcher, launcher.activated_abilities[0])
