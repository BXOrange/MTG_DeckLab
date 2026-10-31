"""Saradoc's Halfling token must not re-trigger Saradoc (RULE 111.9 / 603.2) — report 20261022T220548."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.cards.card import Card
from tests.support.catalogue import battlefield_object


def _board():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    for name, type_line in (
        ("Saradoc, Master of Buckland", "Creature — Halfling Noble"),
        ("Mirkwood Bats", "Creature — Bat"),
    ):
        obj = battlefield_object(engine, "p1", name, type_line, is_creature=True, power=2, toughness=2)
        bind_from_catalogue(obj)
    return engine


def _enter(engine, name, power):
    card = Card(id=name, name=name, type_line="Creature — Elf", is_creature=True, power=power, toughness=power)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    engine.state.player_by_id("p1").add_to_zone(obj, Zone.HAND)
    engine.cast_spell(engine.state.player_by_id("p1"), obj)
    engine.resolve_until_stable()


def _halflings(engine):
    return [o for o in engine.state.battlefield if o.name == "Halfling" and o.is_token]


def test_small_nontoken_creature_makes_exactly_one_halfling_and_it_terminates():
    engine = _board()
    _enter(engine, "Small Elf", 2)
    assert len(_halflings(engine)) == 1
    assert engine.state.player_by_id("p2").life == 19  # Mirkwood Bats: one token created


def test_big_nontoken_creature_does_not_trigger_saradoc():
    engine = _board()
    _enter(engine, "Big Elf", 3)
    assert not _halflings(engine)
