"""Shared builders for catalogue card tests."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def two_player_game() -> tuple[GameEngine, object]:
    engine = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_hand=0, starting_life=20,
    )
    return engine, engine.state.active_player


def battlefield_object(engine: GameEngine, player_id: str, name: str, type_line: str, **kwargs) -> GameObject:
    obj = GameObject(
        card=Card(id=name.replace(" ", ""), name=name, type_line=type_line, **kwargs),
        owner_id=player_id,
        zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player_id
    engine.state.add_to_battlefield(obj)
    return obj
