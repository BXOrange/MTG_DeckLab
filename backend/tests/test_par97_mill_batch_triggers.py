"""PAR-97 — a mill instruction is one typed graveyard-entry batch."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.effects.returns_graveyards import LoseLifeForMilledCardTypesEffect
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)


def test_mill_emits_one_typed_batch_for_the_actual_moved_cards():
    engine = _engine()
    player = engine.state.player_by_id("p1")
    creature = Card(id="creature", name="Creature", type_line="Creature — Bear", is_creature=True)
    land = Card(id="land", name="Land", type_line="Basic Land — Island", is_land=True)
    player.library.extend([
        GameObject(land, owner_id="p1", zone=Zone.LIBRARY),
        GameObject(creature, owner_id="p1", zone=Zone.LIBRARY),
    ])
    seen: list[GameEvent] = []
    engine.state.subscribe(lambda event: seen.append(event) if event.type == EventType.CARDS_MILLED else None)

    engine.rules.mill(player, 2)

    assert len(seen) == 1
    assert seen[0]["player_id"] == "p1"
    assert "creature" in seen[0]["cards"][0]["object_types"]
    assert "land" in seen[0]["cards"][1]["object_types"]


def test_par97_batch_trigger_cards_parse_against_the_aggregate_event():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name, wanted_type in (("Devourer of Memory", None), ("Sidisi, Brood Tyrant", "creature")):
        parsed = parse_oracle(db.get_card(name))
        assert parsed.coverage != UNMODELED
        trigger = next(spec.trigger for spec in parsed.specs if spec.trigger.get("event") == "CARDS_MILLED")
        assert trigger["condition"] == {"subject": "you"}
        assert trigger.get("milled_card_type") == wanted_type

    for name in (
        "Colossal Grave-Reaver", "Creeping Chill", "Hedge Shredder", "Narcomoeba",
        "Pedantic Learning", "Polluted Cistern",
    ):
        assert parse_oracle(db.get_card(name)).coverage != UNMODELED


def test_polluted_cistern_counts_distinct_types_from_the_firing_batch_only():
    engine = _engine()
    p1, p2 = engine.state.players
    source = GameObject(Card(id="source", name="Source", type_line="Enchantment"), p1.id, Zone.BATTLEFIELD)
    source.controller_id = p1.id
    engine.state.add_to_battlefield(source)
    context = GameContext(engine.state, engine.rules)
    context.trigger_event = GameEvent(EventType.CARDS_MILLED, cards=[
        {"object_types": ["creature", "permanent"]},
        {"object_types": ["land", "permanent"]},
        {"object_types": ["creature", "permanent"]},
    ])

    LoseLifeForMilledCardTypesEffect(source=source).apply(context)

    assert p2.life == 38
