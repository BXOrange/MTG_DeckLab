"""Shared builders for the Star Trek one-off card tests (real cached cards on a real engine)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card

#: Generic mana that comfortably pays any single Star Trek test card's mana cost.
PAYMENT_MANA = 12

#: Mana of each colour given per cast, enough for any double-pip cost in these tests.
COLORED_MANA = 3

#: Upper bound on step advances from declare attackers to end of combat.
COMBAT_STEP_LIMIT = 8

#: Library size that survives the draw steps of a walked-through turn.
STEP_WALK_LIBRARY = 5

#: Upper bound on step advances while walking a turn to a named step.
STEP_ADVANCE_LIMIT = 20


def game(*hand_names: str, via_steps: bool = False, stop_at: str = "main1"):
    """A two-player game on p1's turn, main phase 1, with ``hand_names`` (real cached cards) in p1's hand.

    ``via_steps`` walks the real step sequence to main 1 (needed before ``attack``, since ``advance_step`` only
    continues correctly from a started game); libraries are stocked so the draw step cannot deck anyone.
    """
    cards = [get_cached_card(name) for name in hand_names]
    assert all(cards), f"card missing from the test cache: {hand_names}"
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.player_by_id("p1").hand:
        bind_from_catalogue(obj)
    if via_steps:
        for pid in ("p1", "p2"):
            stock_library(engine, pid, STEP_WALK_LIBRARY)
        engine.start()
        advance_to(engine, stop_at)
    else:
        engine.begin_turn()
        engine.state.current_step = "main1"
    return engine, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def advance_to(engine: GameEngine, step: str) -> None:
    """Advance the real turn structure until ``step`` begins (its beginning-of-step triggers are queued)."""
    for _ in range(STEP_ADVANCE_LIMIT):
        if engine.state.current_step == step:
            return
        engine.advance_step()
    raise AssertionError(f"never reached step {step!r}; stuck at {engine.state.current_step!r}")


def on_battlefield(engine: GameEngine, player_id: str, name: str) -> GameObject:
    """Put the real cached card ``name`` on the battlefield (bound, not summoning sick) without casting it."""
    card = get_cached_card(name)
    assert card is not None, name
    obj = GameObject(card, owner_id=player_id, zone=Zone.BATTLEFIELD)
    obj.controller_id = player_id
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    return obj


def vanilla(engine: GameEngine, player_id: str, name: str = "Bear", power: int = 2, toughness: int = 2) -> GameObject:
    """A plain creature already on the battlefield."""
    obj = GameObject(
        Card(id=name.replace(" ", ""), name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=player_id, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = player_id
    obj.summoning_sick = False
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    return obj


def cast(engine: GameEngine, player, obj: GameObject, **kwargs) -> None:
    """Pay with plentiful mana, cast ``obj`` from hand and resolve everything it puts on the stack."""
    player.mana_pool.add_many({"C": PAYMENT_MANA, "W": COLORED_MANA, "U": COLORED_MANA, "B": COLORED_MANA,
                               "R": COLORED_MANA, "G": COLORED_MANA})
    engine.cast_spell(player, obj, **kwargs)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def stock_library(engine: GameEngine, player_id: str, count: int, type_line: str = "Land") -> list[GameObject]:
    """Fill the library with ``count`` plain cards (top of library is the end of the list)."""
    player = engine.state.player_by_id(player_id)
    made = []
    for i in range(count):
        obj = GameObject(Card(id=f"L{player_id}{i}", name=f"Lib {player_id} {i}", type_line=type_line,
                              is_land=type_line == "Land"), owner_id=player_id, zone=Zone.LIBRARY)
        player.library.append(obj)
        made.append(obj)
    return made


def attack(engine: GameEngine, player, *attackers: GameObject) -> None:
    """Declare ``attackers`` against the opponent and run combat to its end (game built with ``via_steps=True``)."""
    while engine.state.current_step != "declare_attackers":
        engine.advance_step()
    defender = engine.legal_defenders_for(player)[0]
    for obj in attackers:
        obj.summoning_sick = False
    engine.declare_attackers(player, [{"attacker": a, "defender": defender} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for _ in range(COMBAT_STEP_LIMIT):  # bounded so a stuck step fails fast
        engine.advance_step()
        if engine.state.current_step == "end_combat":
            break
    engine.resolve_until_stable()
