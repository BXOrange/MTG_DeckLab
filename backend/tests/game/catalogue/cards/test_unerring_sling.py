"""Unerring Sling retains its chosen cost creature and measures power on resolution."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase


def _board():
    engine = game()
    main_phase(engine)
    player = engine.state.player_by_id("p1")
    sling = card(engine, "Unerring Sling")
    helper = filler(engine, "Helper", power=3, toughness=4)
    target = filler(engine, "Target", player="p2", power=2, toughness=20)
    target.intrinsic_keywords.add("flying")
    target.attacking = True
    player.mana_pool.add("C", 3)
    return engine, player, sling, helper, target


def _activate(engine, player, sling, helper, target):
    engine.activate_ability(player, sling, targets=[target], tap_choices=[helper.instance_id])


def test_pays_full_cost_and_sling_deals_the_chosen_creatures_power():
    engine, player, sling, helper, target = _board()
    stronger = filler(engine, "Stronger", power=7, toughness=8)
    a, b = specs_for(sling.card), specs_for(sling.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    _activate(engine, player, sling, helper, target)
    assert sling.tapped and helper.tapped and not stronger.tapped and player.mana_pool.total() == 0
    assert target.damage_marked == 0
    engine.resolve_until_stable()
    assert target.damage_marked == 3
    hits = [event for event in engine.state.events_this_turn() if event.type == EventType.DAMAGE]
    assert hits[0].get("source_id") == sling.instance_id and not hits[0].get("combat")


def test_uses_current_power_when_cost_creature_is_still_on_battlefield():
    engine, player, sling, helper, target = _board()
    _activate(engine, player, sling, helper, target)
    engine.rules.add_counters(helper, 2, "+1/+1")
    engine.resolve_until_stable()
    assert target.damage_marked == 5


def test_departed_creature_uses_last_known_power_even_after_returning():
    engine, player, sling, helper, target = _board()
    _activate(engine, player, sling, helper, target)
    engine.rules.add_counters(helper, 2, "+1/+1")
    engine.recompute_continuous_effects()
    engine.rules.exile(helper)
    engine.rules.return_from_graveyard(helper, "battlefield")
    engine.rules.add_counters(helper, 10, "+1/+1")
    engine.resolve_until_stable()
    assert target.damage_marked == 5


@pytest.mark.parametrize("bad", ["no_flying", "idle", "tapped_helper", "opponents_helper"])
def test_invalid_target_or_payment_is_rejected_without_tapping_sling(bad):
    engine, player, sling, helper, target = _board()
    if bad == "no_flying":
        target.intrinsic_keywords.clear()
    elif bad == "idle":
        target.attacking = False
    elif bad == "tapped_helper":
        helper.tapped = True
    else:
        helper.controller_id = "p2"
    with pytest.raises(ValueError):
        _activate(engine, player, sling, helper, target)
    assert not sling.tapped and player.mana_pool.total() == 3


def test_blocking_flying_creature_is_legal_and_summoning_sickness_does_not_prevent_cost():
    engine, player, sling, helper, target = _board()
    target.attacking = False
    target.blocking = helper.instance_id
    helper.summoning_sick = True
    _activate(engine, player, sling, helper, target)
    engine.resolve_until_stable()
    assert target.damage_marked == 3


def test_overlapping_activations_keep_different_payment_creatures():
    engine, player, sling, helper, target = _board()
    other = filler(engine, "Other helper", power=6, toughness=7)
    _activate(engine, player, sling, helper, target)
    engine.rules.set_tapped(sling, False)
    player.mana_pool.add("C", 3)
    _activate(engine, player, sling, other, target)
    engine.rules.resolve_top_of_stack()
    assert target.damage_marked == 6
    engine.resolve_until_stable()
    assert target.damage_marked == 9


def test_clone_retains_the_paid_creature_visit():
    engine, player, sling, helper, target = _board()
    _activate(engine, player, sling, helper, target)
    clone = GameEngine(engine.state.clone())
    clone.resolve_until_stable()
    assert clone.state.find_object(target.instance_id).damage_marked == 3 and target.damage_marked == 0
