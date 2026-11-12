"""Real casts, opponent decisions, and dynamic blocking restrictions."""
import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, cast, filler, game


@pytest.fixture(params=["Goblin War Cry", "Eunuchs' Intrigues"])
def board(request):
    engine = game(players=3)
    spell = card(engine, request.param, zone=Zone.HAND)
    opponent = engine.state.player_by_id("p2")
    a = filler(engine, "Chosen", player="p2", power=2, toughness=3)
    b = filler(engine, "Other", player="p2", power=2, toughness=3)
    attacker = filler(engine, "Attacker", power=2, toughness=3)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    return engine, spell, opponent, a, b, attacker


def _choose(engine, obj):
    engine.resolve_pending_choice(str(obj.instance_id))
    engine.resolve_until_stable()


def test_opponent_chooses_without_targeting_creature(board):
    engine, spell, opponent, a, b, attacker = board
    a.temp_keywords.update({"hexproof", "shroud"})
    engine.recompute_continuous_effects()
    first, second = specs_for(spell.card), specs_for(spell.card)
    assert first[0] is not second[0] and first[0].effects[0] is not second[0].effects[0]
    assert len(spell.spell_effects) == 1
    cast(engine, spell, targets=[opponent])
    pending = engine.state.pending_choice
    assert pending["player_id"] == "p2" and not pending["optional"]
    assert {o["instance_id"] for o in pending["options"]} == {a.instance_id, b.instance_id}
    _choose(engine, a)
    assert engine.can_block(opponent, a, attacker)
    assert not engine.can_block(opponent, b, attacker)
    assert spell.zone == Zone.GRAVEYARD


def test_late_arrivals_and_control_changes_are_affected(board):
    engine, spell, opponent, a, b, attacker = board
    outsider = filler(engine, "Third player's creature", player="p3", power=2, toughness=3)
    cast(engine, spell, targets=[opponent])
    _choose(engine, a)
    newcomer = filler(engine, "Newcomer", player="p2", power=2, toughness=3)
    assert not engine.can_block(opponent, newcomer, attacker)
    outsider.controller_id = "p2"
    assert not engine.can_block(opponent, outsider, attacker)
    b.controller_id = "p3"
    attacker.combat_defender = {"kind": "player", "id": "p3"}
    assert engine.can_block(engine.state.player_by_id("p3"), b, attacker)


def test_chosen_creature_blink_loses_exception(board):
    engine, spell, opponent, a, b, attacker = board
    cast(engine, spell, targets=[opponent])
    _choose(engine, a)
    engine.rules.put_into_graveyard(a)
    engine.rules.return_from_graveyard(a, "battlefield")
    assert not engine.can_block(opponent, a, attacker)


def test_cleanup_expires_restriction(board):
    engine, spell, opponent, a, b, attacker = board
    cast(engine, spell, targets=[opponent])
    _choose(engine, a)
    engine._step_cleanup()
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    assert engine.can_block(opponent, b, attacker)


def test_pending_choice_and_rule_survive_clone(board):
    engine, spell, opponent, a, b, attacker = board
    cast(engine, spell, targets=[opponent])
    clone = GameEngine(engine.state.clone())
    clone.resolve_pending_choice(str(a.instance_id))
    clone.resolve_until_stable()
    assert engine.state.pending_choice is not None
    clone2 = GameEngine(clone.state.clone())
    assert not clone2.can_block(clone2.state.player_by_id("p2"),
                                clone2.state.find_object(b.instance_id), clone2.state.find_object(attacker.instance_id))


def test_empty_opponent_board_still_restricts_later_creatures():
    engine = game()
    spell = card(engine, "Goblin War Cry", zone=Zone.HAND)
    opponent = engine.state.player_by_id("p2")
    cast(engine, spell, targets=[opponent])
    assert engine.state.pending_choice is None
    newcomer = filler(engine, "Newcomer", player="p2", power=2, toughness=3)
    attacker = filler(engine, "Attacker", power=2, toughness=3)
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    assert not engine.can_block(opponent, newcomer, attacker)


def test_invalid_choice_preserves_decision(board):
    engine, spell, opponent, a, b, attacker = board
    cast(engine, spell, targets=[opponent])
    with pytest.raises(ValueError):
        engine.resolve_pending_choice(str(attacker.instance_id))
    assert engine.state.pending_choice["player_id"] == "p2"
    assert not engine.state.floating_statics
    _choose(engine, b)
    assert engine.can_block(opponent, b, attacker)
    assert not engine.can_block(opponent, a, attacker)


def test_can_target_only_an_opponent(board):
    engine, spell, opponent, a, b, attacker = board
    from mtg_analyzer.game.targeting import spell_target_specs, legal_targets
    spec, = spell_target_specs(spell)
    options = legal_targets(engine.state, "p1", spec, source=spell)
    assert {o["player_id"] for o in options} == {"p2", "p3"}
