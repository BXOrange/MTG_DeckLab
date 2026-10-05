"""Weathered Sentinels: defender permission against the right player's own turn."""

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.card_registry import specs_for
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _game, _card
from tests.support.catalogue import battlefield_object


def _to(engine, player_id, step):
    for _ in range(200):
        if engine.state.active_player.id == player_id and engine.state.current_step == step:
            return
        engine.advance_step()
    raise AssertionError("did not reach the requested turn/step")


def _position(target="player"):
    engine = _game(seats=3)
    sentinel = _card(engine, "Weathered Sentinels")
    attacker = battlefield_object(engine, "p2", "Attacker", "Creature", is_creature=True,
                                  power=1, toughness=2)
    own_walker = battlefield_object(engine, "p1", "Own walker", "Planeswalker", loyalty=9)
    other_walker = battlefield_object(engine, "p2", "Other walker", "Planeswalker", loyalty=9)
    _to(engine, "p2", "declare_attackers")
    if target is not None:
        defender = engine.state.player_by_id("p1") if target == "player" else own_walker
        engine.declare_attackers(engine.state.player_by_id("p2"), [{"attacker": attacker, "defender": defender}])
    _to(engine, "p1", "declare_attackers")
    return engine, sentinel, attacker, other_walker


def test_permission_uses_each_opponents_own_last_turn_and_only_player_defenders():
    engine, sentinel, _, walker = _position()
    p1, p2, p3 = [engine.state.player_by_id(f"p{i}") for i in (1, 2, 3)]
    assert combat.has_defender(sentinel)
    assert engine.state.attacked_player_during_last_turn(p2.id, p1.id)
    assert not engine.state.attacked_player_during_last_turn(p3.id, p1.id)
    assert engine._can_attack(p1, sentinel, p2)
    assert not engine._can_attack(p1, sentinel, p3)
    assert not engine._can_attack(p1, sentinel, p2, defender_kind="planeswalker")
    offer = next(a for a in engine.legal_actions(p1) if a.get("instance_id") == sentinel.instance_id and a["type"] == "attack")
    assert [(d["kind"], d.get("id")) for d in offer["legal_defenders"]] == [("player", p2.id)]
    with pytest.raises(ValueError):
        engine.declare_attackers(p1, [{"attacker": sentinel, "defender": walker}])
    engine.declare_attackers(p1, [{"attacker": sentinel, "defender": p2}])
    assert not sentinel.tapped  # Vigilance is preserved.
    engine.resolve_until_stable()
    assert (sentinel.power, sentinel.toughness) == (5, 8)
    assert combat.has_indestructible(sentinel)
    assert combat.has_defender(sentinel) and combat.has_reach(sentinel) and combat.has_trample(sentinel)


@pytest.mark.parametrize("target", [None, "planeswalker"])
def test_no_permission_without_an_attack_on_you(target):
    engine, sentinel, _, _ = _position(target)
    p1 = engine.state.player_by_id("p1")
    assert not engine._can_attack(p1, sentinel)
    assert not any(a["type"] == "attack" and a.get("instance_id") == sentinel.instance_id
                   for a in engine.legal_actions(p1))


def test_permission_expires_when_the_opponents_next_turn_has_no_attack():
    engine, sentinel, _, _ = _position()
    _to(engine, "p2", "declare_attackers")
    _to(engine, "p1", "declare_attackers")
    assert not engine._can_attack(engine.state.player_by_id("p1"), sentinel)


def test_weathered_specs_are_fresh():
    engine = _game()
    sentinel = _card(engine, "Weathered Sentinels")
    first = specs_for(sentinel.card)
    first[0].effects[0].params["condition"]["kind"] = "invalid"
    assert specs_for(sentinel.card)[0].effects[0].params["condition"]["kind"] == "opponent_attacked_you_last_turn"


def test_goad_does_not_require_an_attack_on_an_ineligible_player():
    engine, sentinel, _, _ = _position()
    sentinel.goaded_by.add("p2")
    engine.declare_attackers(engine.state.player_by_id("p1"), [
        {"attacker": sentinel, "defender": engine.state.player_by_id("p2")},
    ])
    engine.advance_step()  # The only eligible player was the goader.


def test_losing_defender_removes_the_need_for_the_conditional_permission():
    from mtg_analyzer.game.effects.core import EffectRegistry

    engine, sentinel, _, walker = _position(None)
    loss = EffectRegistry.create("remove_keyword", {"affects": "self", "keywords": ["defender"]})
    loss.source = sentinel
    sentinel.static_effects.append(loss)
    engine.recompute_continuous_effects()
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    assert not combat.has_defender(sentinel)
    assert engine._can_attack(p1, sentinel, p2, defender_kind="planeswalker")
    engine.declare_attackers(p1, [{"attacker": sentinel, "defender": walker}])


def test_put_into_combat_attacking_does_not_count_as_an_attack_declaration():
    engine, sentinel, attacker, _ = _position(None)
    _to(engine, "p2", "declare_attackers")
    assert engine.rules.put_onto_battlefield_attacking(attacker, {"kind": "player", "id": "p1"})
    _to(engine, "p1", "declare_attackers")
    assert not engine.state.attacked_player_during_last_turn("p2", "p1")
    assert not engine._can_attack(engine.state.player_by_id("p1"), sentinel)


def test_last_opponent_turn_permission_survives_state_clone():
    from mtg_analyzer.game.game_engine import GameEngine

    engine, sentinel, _, _ = _position()
    restored = GameEngine(engine.state.clone())
    clone = restored.state.find_object(sentinel.instance_id)
    assert restored._can_attack(restored.state.player_by_id("p1"), clone,
                                restored.state.player_by_id("p2"))
    assert not restored._can_attack(restored.state.player_by_id("p1"), clone,
                                    restored.state.player_by_id("p3"))
