"""Shared game-test factories."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.mana.mana_cost import ManaCost


def land(name: str = "Forest", produces: str = "Forest") -> Card:
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def creature(
    name: str = "Grizzly Bears", cost: str = "{1}{G}", power: int = 2,
    toughness: int = 2, **kwargs,
) -> Card:
    return Card(
        id=name,
        name=name,
        type_line=kwargs.pop("type_line", "Creature — Bear"),
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        **kwargs,
    )


def instant(name: str = "Shock", cost: str = "{R}") -> Card:
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )


def make_engine(p1_cards, p2_cards=None, life: int = 20, hand: int = 0) -> GameEngine:
    libraries = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libraries.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libraries, starting_life=life, starting_hand=hand)


def obj_on_battlefield(
    state: GameState, engine: GameEngine, card: Card, controller: str = "p1",
) -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj
