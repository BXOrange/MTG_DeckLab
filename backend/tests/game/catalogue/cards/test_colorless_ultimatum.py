"""Colorless Ultimatum (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Colorless Ultimatum'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


def _main(engine):
    for _ in range(10):
        if engine.state.current_step == "main1": return
        engine.advance_step()


def _cast(engine):
    player = engine.state.players[0]
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add("C", 7)
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()


def test_end_to_end():
    engine = _game(3)
    player = engine.state.players[0]
    bear = _card(engine, "Grizzly Bears")
    bear.summoning_sick = False
    enemy = _card(engine, "Grizzly Bears", player="p2")
    _card(engine, "Forest", player="p3", zone=Zone.LIBRARY)
    _main(engine)
    before = [len(p.library) for p in engine.state.players]
    _cast(engine)
    assert len(player.library) == before[0]
    for i in (1, 2):
        assert len(engine.state.players[i].library) == before[i] // 2
        assert len(engine.state.players[i].exile) == (before[i] + 1) // 2
    assert len(bear._granted_triggered_abilities) == 1
    assert not enemy._granted_triggered_abilities
    late = _card(engine, "Grizzly Bears")
    engine.recompute_continuous_effects()
    assert not late._granted_triggered_abilities
    for _ in range(10):
        if engine.state.current_step == "declare_attackers": break
        engine.advance_step()
    engine.declare_attackers(player, [{"attacker": bear, "defender": {"kind": "player", "id": "p2"}}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert enemy.zone == Zone.GRAVEYARD


def test_two_resolutions_grant_two_instances_and_expire_at_cleanup():
    engine = _game()
    bear = _card(engine, "Grizzly Bears")
    _main(engine)
    _cast(engine)
    _cast(engine)
    assert len(bear._granted_triggered_abilities) == 2
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.active_player.id == "p2": break
    engine.recompute_continuous_effects()
    assert not bear._granted_triggered_abilities
