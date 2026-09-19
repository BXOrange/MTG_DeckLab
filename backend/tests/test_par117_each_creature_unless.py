"""PAR-117 — leading per-creature "unless" iteration."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _card(name: str):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None
    return card


def _spell(engine, name: str, player_id: str) -> GameObject:
    obj = GameObject(_card(name), owner_id=player_id, zone=Zone.HAND)
    bind_from_catalogue(obj)
    engine.state.player_by_id(player_id).hand.append(obj)
    return obj


def _permanent(engine, name: str, player_id: str, *, creature: bool) -> GameObject:
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature" if creature else "Artifact",
             is_creature=creature, power=3 if creature else None,
             toughness=3 if creature else None),
        owner_id=player_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player_id
    engine.state.add_to_battlefield(obj)
    return obj


def _main_phase(engine):
    while engine.state.current_phase != "precombat_main":
        engine.advance_step()
    engine.state.active_player_index = 0


def test_fade_away_and_killing_wave_parse_as_unscoped_per_creature_loops():
    for name in ("Fade Away", "Killing Wave"):
        result = parse_oracle(_card(name))
        assert result.modeled, result.unclaimed
        loop = result.specs[0].effects[0]
        assert loop.type == "for_each"
        assert loop.params["over"] == {"selector": "all_creatures"}


def test_killing_wave_decline_sacrifices_that_iterated_creature():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    p1, p2 = eng.state.players
    wave = _spell(eng, "Killing Wave", p1.id)
    victim = _permanent(eng, "Victim", p2.id, creature=True)
    _main_phase(eng)
    p1.mana_pool.add_many({"B": 1, "C": 2})

    eng.cast_spell(p1, wave, x=2)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_cost_then"
    assert choice["player_id"] == p2.id
    eng.resolve_pending_choice("decline")
    assert victim in p2.graveyard


def test_fade_away_decline_asks_that_creatures_controller_for_a_permanent():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    p1, p2 = eng.state.players
    fade = _spell(eng, "Fade Away", p1.id)
    creature = _permanent(eng, "Creature", p2.id, creature=True)
    artifact = _permanent(eng, "Artifact", p2.id, creature=False)
    _main_phase(eng)
    p1.mana_pool.add_many({"U": 1, "C": 2})
    p2.mana_pool.add("C", 1)

    eng.cast_spell(p1, fade)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("decline")
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    assert choice["player_id"] == p2.id
    eng.resolve_pending_choice(artifact.instance_id)
    assert artifact in p2.graveyard
    assert creature in eng.state.battlefield
