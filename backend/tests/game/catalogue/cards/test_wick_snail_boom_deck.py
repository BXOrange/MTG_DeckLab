"""Hand-authored cards of the saved "Wick Snail Boom" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1


def _blink_spell(name, creature_type_line):
    engine, p1 = _game(name)
    creature = battlefield_object(engine, "p1", "Blinked", creature_type_line, is_creature=True, power=2, toughness=2)
    creature.counters["-1/-1"] = 1  # a counter proves the blink made a new object
    hand_before = len(p1.hand)
    p1.mana_pool.add_many({"U": 1, "C": p1.hand[0].card.converted_mana_cost - 1})
    engine.cast_spell(p1, p1.hand[0], targets=[creature])
    engine.resolve_until_stable()
    return engine, p1, creature, hand_before


def test_sirens_ruse_blinks_and_draws_only_for_a_pirate():
    engine, p1, creature, hand_before = _blink_spell("Siren's Ruse", "Creature — Human Pirate")
    assert creature in engine.state.battlefield and not creature.counters  # returned as a new object
    assert len(p1.hand) == hand_before - 1 + 1  # the spell leaves, one card is drawn

    engine, p1, creature, hand_before = _blink_spell("Siren's Ruse", "Creature — Human Wizard")
    assert creature in engine.state.battlefield
    assert len(p1.hand) == hand_before - 1  # no draw for a non-Pirate


def test_essence_flux_blinks_and_adds_a_counter_only_to_a_spirit():
    engine, p1, spirit, _ = _blink_spell("Essence Flux", "Creature — Spirit")
    assert spirit in engine.state.battlefield
    assert spirit.counters.get("+1/+1", 0) == 1 and not spirit.counters.get("-1/-1")

    engine, p1, human, _ = _blink_spell("Essence Flux", "Creature — Human")
    assert human in engine.state.battlefield and not human.counters
