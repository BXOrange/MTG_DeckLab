"""ENG-56: RULE 208.3 off-battlefield power/toughness (CR 2026-11-06).

A noncreature card off the battlefield has P/T only if its printed P/T is not part of an ability: a Vehicle keeps
it, a Spacecraft (Station, P/T inside the station ability) has none.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.cards.card_query import matches as card_matches
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue
from tests.support.card_cache import get_cached_card
from tests.support.game import creature

STATION_TEXT = (
    "Station (Tap another creature you control: Put charge counters equal to its power on this Spacecraft. "
    "Station only as a sorcery. It's an artifact creature at 3+.)\n3+ | Flying"
)


def _spacecraft() -> Card:
    return Card(id="sc", name="Test Cruiser", type_line="Artifact — Spacecraft", keywords=["Station"],
                oracle_text=STATION_TEXT, vehicle_power=3, vehicle_toughness=4)


def _vehicle() -> Card:
    return Card(id="vh", name="Test Copter", type_line="Artifact — Vehicle", keywords=["Crew"],
                oracle_text="Crew 1", vehicle_power=3, vehicle_toughness=3)


def test_card_helpers_distinguish_vehicle_from_spacecraft():
    assert (_vehicle().off_battlefield_power, _vehicle().off_battlefield_toughness) == (3, 3)
    assert (_spacecraft().off_battlefield_power, _spacecraft().off_battlefield_toughness) == (None, None)
    bear = creature()
    assert (bear.off_battlefield_power, bear.off_battlefield_toughness) == (2, 2)


def test_search_filters_skip_spacecraft_but_not_vehicle():
    for crit in ({"max_power": 3}, {"min_power": 3}, {"max_toughness": 4}, {"min_toughness": 1}):
        assert not card_matches(_spacecraft(), crit)
        assert card_matches(_vehicle(), crit)
    assert not card_matches(_vehicle(), {"min_power": 4})
    assert card_matches(creature(), {"type": "Creature", "max_power": 2})


def _engine():
    return GameEngine.new_game([("p1", "A", [creature()] * 3), ("p2", "B", [creature()] * 3)],
                               starting_hand=0, starting_life=20)


def test_object_power_off_battlefield_by_zone():
    engine = _engine()
    p1 = engine.state.player_by_id("p1")
    for zone, attr in ((Zone.HAND, "hand"), (Zone.GRAVEYARD, "graveyard"), (Zone.LIBRARY, "library")):
        ship = GameObject(_spacecraft(), owner_id="p1", zone=zone)
        van = GameObject(_vehicle(), owner_id="p1", zone=zone)
        getattr(p1, attr).extend([ship, van])
        assert (ship.power, ship.toughness) == (None, None)
        assert (van.power, van.toughness) == (3, 3)
        assert ship.to_dict()["power"] is None and van.to_dict()["power"] == 3


def test_battlefield_noncreature_has_no_pt_and_station_threshold_still_animates():
    # Real Spacecraft: RULE 722.2 station brackets come from the bound card, not hand-built text.
    engine = _engine()
    ship = GameObject(get_cached_card("Entropic Battlecruiser"), owner_id="p1", zone=Zone.BATTLEFIELD)
    ship.controller_id = "p1"
    bind_from_catalogue(ship)
    van = GameObject(_vehicle(), owner_id="p1", zone=Zone.BATTLEFIELD)
    van.controller_id = "p1"
    engine.state.add_to_battlefield(ship)
    engine.state.add_to_battlefield(van)
    engine.recompute_continuous_effects()
    # RULE 208.3: a noncreature permanent has no P/T, Vehicle included.
    assert ship.power is None and van.power is None
    ship.counters["charge"] = 8
    engine.recompute_continuous_effects()
    assert ship.is_creature
    assert (ship.power, ship.toughness) == (3, 10)
