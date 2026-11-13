"""Infernal Harvest pays X Swamp returns and divides the announced X damage."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, card, filler, game, main_phase


def _board(count=3):
    engine = game()
    spell = card(engine, "Infernal Harvest", zone=Zone.HAND)
    player = engine.state.player_by_id("p1")
    swamps = [filler(engine, f"Swamp {i}", type_line="Basic Land — Swamp") for i in range(count)]
    targets = [filler(engine, f"Victim {i}", player="p2", power=2, toughness=5) for i in range(2)]
    main_phase(engine)
    player.mana_pool.add_many(RICH)
    return engine, player, spell, swamps, targets


def test_returns_selected_swamps_before_damage_and_preserves_division():
    engine, player, spell, swamps, targets = _board()
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    engine.cast_spell(player, spell, x=3, targets=targets,
                      sacrifice_choices=[obj.instance_id for obj in swamps], damage_divisions={"0": [1, 2]})
    assert all(obj in player.hand for obj in swamps)
    assert spell.zone == Zone.STACK and all(obj.damage_marked == 0 for obj in targets)
    engine.resolve_until_stable()
    assert [obj.damage_marked for obj in targets] == [1, 2]
    assert spell.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("bad", ["too_many", "duplicate", "wrong_type", "opponent"])
def test_invalid_return_payment_does_not_move_cards_or_spend_mana(bad):
    engine, player, spell, swamps, targets = _board()
    island = filler(engine, "Island", type_line="Basic Land — Island")
    theirs = filler(engine, "Their Swamp", player="p2", type_line="Basic Land — Swamp")
    ids = {
        "too_many": [swamps[0].instance_id, swamps[1].instance_id, swamps[2].instance_id],
        "duplicate": [swamps[0].instance_id, swamps[0].instance_id],
        "wrong_type": [swamps[0].instance_id, island.instance_id],
        "opponent": [swamps[0].instance_id, theirs.instance_id],
    }[bad]
    mana = player.mana_pool.total()
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, x=2, targets=[targets[0]],
                          sacrifice_choices=ids, damage_divisions={"0": [2]})
    assert spell in player.hand and all(obj.zone == Zone.BATTLEFIELD for obj in swamps)
    assert player.mana_pool.total() == mana


def test_x_zero_requires_no_swamps_and_no_targets():
    engine, player, spell, swamps, targets = _board(0)
    engine.cast_spell(player, spell, x=0, targets=[], sacrifice_choices=[], damage_divisions={"0": []})
    engine.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD and all(obj.damage_marked == 0 for obj in targets)


def test_legal_action_offers_x_bound_and_return_pool():
    engine, player, spell, swamps, targets = _board()
    action = next(a for a in engine.legal_actions(player) if a.get("type") == "cast_spell"
                  and a.get("instance_id") == spell.instance_id)
    assert action["has_x"] and action["max_x"] == 3
    assert action["damage_divisions"][0]["total_from_x"] == 1
    cost = action["sacrifice_count_cost"]
    assert cost["count"] == "x" and cost["verb"] == "return"
    assert {obj["instance_id"] for obj in cost["options"]} == {obj.instance_id for obj in swamps}


def test_stolen_swamp_can_pay_and_returns_to_its_owner():
    engine, player, spell, swamps, targets = _board(0)
    stolen = filler(engine, "Stolen", player="p2", type_line="Land — Swamp")
    stolen.controller_id = "p1"
    engine.cast_spell(player, spell, x=1, targets=[targets[0]],
                      sacrifice_choices=[stolen.instance_id], damage_divisions={"0": [1]})
    engine.resolve_until_stable()
    assert stolen in engine.state.player_by_id("p2").hand and targets[0].damage_marked == 1


def test_more_than_ten_targets_are_allowed_and_each_receives_its_share():
    engine, player, spell, swamps, targets = _board(11)
    targets.extend(filler(engine, f"Extra {i}", player="p2", power=2, toughness=5) for i in range(9))
    engine.cast_spell(player, spell, x=11, targets=targets,
                      sacrifice_choices=[obj.instance_id for obj in swamps], damage_divisions={"0": [1] * 11})
    engine.resolve_until_stable()
    assert all(obj.damage_marked == 1 for obj in targets)


def test_invalid_division_then_zero_x_does_not_reuse_previous_announcement():
    engine, player, spell, swamps, targets = _board()
    with pytest.raises(ValueError):
        engine.cast_spell(player, spell, x=2, targets=targets,
                          sacrifice_choices=[obj.instance_id for obj in swamps[:2]],
                          damage_divisions={"0": [2, 1]})
    assert all(obj.zone == Zone.BATTLEFIELD for obj in swamps)
    engine.cast_spell(player, spell, x=0, targets=[], sacrifice_choices=[], damage_divisions={"0": []})
    engine.resolve_until_stable()
    assert spell.zone == Zone.GRAVEYARD and all(obj.zone == Zone.BATTLEFIELD for obj in swamps)


def test_illegal_target_does_not_refund_returned_swamps_or_reassign_its_damage():
    engine, player, spell, swamps, targets = _board()
    engine.cast_spell(player, spell, x=3, targets=targets,
                      sacrifice_choices=[obj.instance_id for obj in swamps], damage_divisions={"0": [1, 2]})
    engine.rules.exile(targets[0])
    engine.resolve_until_stable()
    assert targets[1].damage_marked == 2 and all(obj in player.hand for obj in swamps)
