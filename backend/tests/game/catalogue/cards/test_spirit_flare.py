"""Spirit Flare's two targets, conditional tap and complete Flashback cost."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, cast, filler, game, main_phase


def _board(zone=Zone.HAND):
    engine = game()
    main_phase(engine)
    player = engine.state.player_by_id("p1")
    spell = card(engine, "Spirit Flare", zone=zone)
    dealer = filler(engine, "Dealer", power=3, toughness=4)
    victim = filler(engine, "Victim", player="p2", power=2, toughness=6)
    victim.attacking = True
    return engine, player, spell, dealer, victim


def test_taps_first_target_and_that_creature_deals_its_power():
    engine, player, spell, dealer, victim = _board()
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cast(engine, spell, targets=[dealer, victim])
    assert dealer.tapped and victim.damage_marked == 3
    hits = [event for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE]
    assert len(hits) == 1 and hits[0].get("source_id") == dealer.instance_id
    assert not hits[0].get("combat")


@pytest.mark.parametrize("change", ["tap", "exile"])
def test_first_target_becoming_illegal_stops_damage(change):
    engine, player, spell, dealer, victim = _board()
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[dealer, victim])
    if change == "tap":
        engine.rules.set_tapped(dealer, True)
    else:
        engine.rules.exile(dealer)
    engine.resolve_until_stable()
    assert victim.damage_marked == 0


def test_second_target_becoming_illegal_still_taps_first():
    engine, player, spell, dealer, victim = _board()
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[dealer, victim])
    victim.attacking = False
    engine.resolve_until_stable()
    assert dealer.tapped and victim.damage_marked == 0


def test_power_is_measured_on_resolution():
    engine, player, spell, dealer, victim = _board()
    player.mana_pool.add_many(RICH)
    engine.cast_spell(player, spell, targets=[dealer, victim])
    engine.rules.add_counters(dealer, 2, "+1/+1")
    engine.resolve_until_stable()
    assert victim.damage_marked == 5


def test_flashback_pays_mana_and_three_life_before_resolution_then_exiles():
    engine, player, spell, dealer, victim = _board(Zone.GRAVEYARD)
    player.mana_pool.add_many({"C": 1, "W": 1})
    engine.cast_spell(player, spell, targets=[dealer, victim])
    assert player.life == 17 and player.mana_pool.total() == 0
    assert spell.zone == Zone.STACK and not dealer.tapped
    engine.resolve_until_stable()
    assert spell.zone == Zone.EXILE and dealer.tapped and victim.damage_marked == 3


def test_insufficient_life_prevents_flashback_without_spending_mana():
    engine, player, spell, dealer, victim = _board(Zone.GRAVEYARD)
    player.life = 2
    player.mana_pool.add_many({"C": 1, "W": 1})
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, targets=[dealer, victim])
    assert player.life == 2 and player.mana_pool.total() == 2 and spell.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("bad", ["tapped_dealer", "own_victim", "idle_victim"])
def test_target_restrictions_are_enforced_before_payment(bad):
    engine, player, spell, dealer, victim = _board()
    if bad == "tapped_dealer":
        dealer.tapped = True
    elif bad == "own_victim":
        victim.controller_id = "p1"
    else:
        victim.attacking = False
    with pytest.raises(ValueError):
        cast(engine, spell, targets=[dealer, victim])
    assert spell.zone == Zone.HAND and victim.damage_marked == 0


def test_clone_keeps_both_targets_and_paid_flashback_cost():
    engine, player, spell, dealer, victim = _board(Zone.GRAVEYARD)
    player.mana_pool.add_many({"C": 1, "W": 1})
    engine.cast_spell(player, spell, targets=[dealer, victim])
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(victim.instance_id).damage_marked == 3
    assert clone.state.find_object(spell.instance_id).zone == Zone.EXILE
    assert clone.state.player_by_id("p1").life == 17
    assert victim.damage_marked == 0
