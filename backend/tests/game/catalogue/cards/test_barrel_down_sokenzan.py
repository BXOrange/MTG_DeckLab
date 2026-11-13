"""Barrel Down Sokenzan's sweep choices and measured damage."""
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


def _board():
    engine = game()
    spell = card(engine, "Barrel Down Sokenzan", zone=Zone.HAND)
    target = filler(engine, "Target", player="p2", power=2, toughness=8)
    mountains = [filler(engine, f"Mountain {i}", type_line="Basic Land — Mountain") for i in range(3)]
    island = filler(engine, "Island", type_line="Basic Land — Island")
    theirs = filler(engine, "Their Mountain", player="p2", type_line="Basic Land — Mountain")
    return engine, spell, target, mountains, island, theirs


def _pick(engine, obj):
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects"
    option = next(option for option in choice["options"] if option.get("instance_id") == obj.instance_id)
    engine.resolve_pending_choice(str(option["id"]))


def test_return_two_mountains_deals_four_and_excludes_other_lands():
    engine, spell, target, mountains, island, theirs = _board()
    a, b = specs_for(spell.card), specs_for(spell.card)
    assert a[0] is not b[0] and a[0].effects[0] is not b[0].effects[0]
    cast(engine, spell, targets=[target])
    pool = {option.get("instance_id") for option in engine.state.pending_choice["options"]}
    assert island.instance_id not in pool and theirs.instance_id not in pool
    _pick(engine, mountains[0])
    _pick(engine, mountains[2])
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert target.damage_marked == 4 and spell.zone == Zone.GRAVEYARD
    assert mountains[0].zone == mountains[2].zone == Zone.HAND
    assert mountains[1].zone == island.zone == theirs.zone == Zone.BATTLEFIELD


def test_return_zero_deals_zero_and_does_not_count_previous_returns():
    engine, spell, target, mountains, island, theirs = _board()
    engine.rules.return_to_hand(mountains[0])
    cast(engine, spell, targets=[target])
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert target.damage_marked == 0


def test_stolen_mountain_returns_to_owner_but_still_counts():
    engine, spell, target, mountains, island, theirs = _board()
    theirs.controller_id = "p1"
    cast(engine, spell, targets=[target])
    _pick(engine, theirs)
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert theirs in engine.state.player_by_id("p2").hand and target.damage_marked == 2


def test_clone_keeps_mid_selection_return_count_and_target():
    engine, spell, target, mountains, island, theirs = _board()
    cast(engine, spell, targets=[target])
    _pick(engine, mountains[0])
    clone = GameEngine(engine.state.clone())
    _pick(clone, clone.state.find_object(mountains[1].instance_id))
    clone.resolve_pending_choice("decline")
    clone.resolve_until_stable()
    assert clone.state.find_object(target.instance_id).damage_marked == 4
    assert target.damage_marked == 0


def test_illegal_target_stops_return_choice_entirely():
    engine, spell, target, mountains, island, theirs = _board()
    player = engine.state.player_by_id("p1")
    engine.state.current_step = "main1"
    player.mana_pool.add_many({"R": 1, "C": 2})
    engine.cast_spell(player, spell, targets=[target])
    engine.rules.exile(target)
    engine.resolve_until_stable()
    assert not engine.state.pending_choice
    assert all(obj.zone == Zone.BATTLEFIELD for obj in mountains)
