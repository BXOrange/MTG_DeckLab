"""BUG-65: "Cumulative upkeep {G} or {W}" lets every age counter's payment choose either symbol.

RULE 702.24a: "If [cost] has choices associated with it, each choice is made separately for each age counter, then
either the entire set of costs is paid, or none of them is paid." The per-counter cost "{G} or {W}" is exactly the
hybrid symbol {G/W} (RULE 107.4e: paid with {G} or {W}), so the alternatives ride the keyword as that hybrid symbol
and the ordinary hybrid payment path pays N of them, each independently chosen.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.keywords import cumulative_upkeep_mana_alternatives
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase
from mtg_analyzer.services.game_session import GameSession

#: Age counters after the first / second upkeep (RULE 702.24a adds one each upkeep).
FIRST_AGE, SECOND_AGE = 1, 2
STARTING_LIFE = 20
#: Mana put in the pool for a payment test, comfortably more than any case spends.
POOL_SURPLUS = 5


def real_card(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None, name
    return card


def engine() -> GameEngine:
    filler = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    return GameEngine.new_game(
        [("p1", "Alice", [filler] * 8), ("p2", "Bob", [filler] * 8)], starting_hand=0, starting_life=STARTING_LIFE,
    )


def put(eng: GameEngine, name: str, age: int = 0) -> GameObject:
    obj = GameObject(real_card(name), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    if age:
        obj.counters["age"] = age
    return obj


def upkeep(target) -> None:
    eng = getattr(target, "engine", target)
    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()


def fund(eng: GameEngine, **mana: int) -> None:
    for color, amount in mana.items():
        eng.state.player_by_id("p1").mana_pool.add(color.upper(), amount)


def on_battlefield(eng: GameEngine, obj: GameObject) -> bool:
    return obj in eng.state.battlefield


# -- parser ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, cost",
    [
        ("Arctic Nishoba", "{G/W}"),
        ("Earthen Goo", "{R/G}"),
        ("Jötun Owl Keeper", "{W/U}"),
        ("Krovikan Whispers", "{U/B}"),
    ],
)
def test_alternatives_are_recorded_as_one_hybrid_symbol(name, cost):
    specs = parse_oracle(real_card(name)).specs
    assert [s.keyword["cost"] for s in specs if (s.keyword or {}).get("name") == "cumulative_upkeep"] == [cost]
    assert parse_oracle(real_card(name)).modeled


def test_alternatives_helper_fails_closed_on_other_shapes():
    assert cumulative_upkeep_mana_alternatives("Cumulative upkeep {G} or {W}") == "{G/W}"
    assert cumulative_upkeep_mana_alternatives("Cumulative upkeep {2} or {W}") is None
    assert cumulative_upkeep_mana_alternatives("Cumulative upkeep {G} or {G}") is None
    assert cumulative_upkeep_mana_alternatives("Cumulative upkeep {G}") is None


# -- engine: each age counter picks its own alternative ------------------------------------------------------------


@pytest.mark.parametrize(
    "mana",
    [{"w": SECOND_AGE}, {"g": 1, "w": 1}, {"g": SECOND_AGE}],
    ids=["WW", "GW", "GG"],
)
def test_nishoba_with_two_age_counters_pays_any_mix(mana):
    eng = engine()
    obj = put(eng, "Arctic Nishoba", age=FIRST_AGE)
    fund(eng, **mana)
    upkeep(eng)
    assert obj.counters["age"] == SECOND_AGE
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    eng.resolve_pending_choice("pay")
    assert on_battlefield(eng, obj)
    assert eng.state.player_by_id("p1").mana_pool.total() == 0


def test_nishoba_is_sacrificed_when_no_mix_is_payable():
    eng = engine()
    obj = put(eng, "Arctic Nishoba", age=FIRST_AGE)
    fund(eng, g=1, r=POOL_SURPLUS)  # only one of the two required {G}/{W} symbols
    upkeep(eng)
    assert eng.state.pending_choice is None  # RULE 118.3: not asked when it cannot pay
    assert not on_battlefield(eng, obj)
    assert obj in eng.state.player_by_id("p1").graveyard


def test_nishoba_declined_is_sacrificed_and_keeps_the_mana():
    eng = engine()
    obj = put(eng, "Arctic Nishoba")
    fund(eng, w=1)
    upkeep(eng)
    eng.resolve_pending_choice("decline")
    assert not on_battlefield(eng, obj)
    assert eng.state.player_by_id("p1").mana_pool.total() == 1


@pytest.mark.parametrize(
    "name, first, second",
    [("Earthen Goo", "r", "g"), ("Jötun Owl Keeper", "w", "u"), ("Krovikan Whispers", "u", "b")],
)
def test_other_cards_accept_either_symbol_per_counter(name, first, second):
    eng = engine()
    obj = put(eng, name, age=FIRST_AGE)
    fund(eng, **{first: 1, second: 1})
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert on_battlefield(eng, obj)
    assert eng.state.player_by_id("p1").mana_pool.total() == 0


def test_other_card_is_sacrificed_with_an_off_color_pool():
    eng = engine()
    obj = put(eng, "Krovikan Whispers")
    fund(eng, g=POOL_SURPLUS)
    upkeep(eng)
    assert not on_battlefield(eng, obj)


# -- GameSession flow and undo -----------------------------------------------------------------------------------


def test_session_pay_and_undo():
    eng = engine()
    obj = put(eng, "Arctic Nishoba", age=FIRST_AGE)
    fund(eng, g=1, w=1)
    session = GameSession(eng)
    upkeep(session)
    assert session.engine.state.pending_choice["kind"] == "sacrifice_unless_pay"
    session.apply_action({"type": "choose", "option_id": "pay"}, "p1")
    assert session.engine.state.player_by_id("p1").mana_pool.total() == 0
    session.rewind(1)  # undo the payment: the offer is open again and the mana is back
    state = session.engine.state
    assert state.player_by_id("p1").mana_pool.total() == SECOND_AGE
    assert state.pending_choice is not None and state.pending_choice["kind"] == "sacrifice_unless_pay"
    session.apply_action({"type": "choose", "option_id": "decline"}, "p1")
    assert not any(o.name == obj.name for o in session.engine.state.battlefield)


# -- affordability and auto-tap from lands -----------------------------------------------------------------------


def basic_land(eng: GameEngine, name: str) -> GameObject:
    card = Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_untapped_lands_pay_a_mixed_alternative_set():
    eng = engine()
    obj = put(eng, "Arctic Nishoba", age=FIRST_AGE)
    lands = [basic_land(eng, "Forest"), basic_land(eng, "Plains")]  # {G} for one counter, {W} for the other
    upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    assert eng.state.pending_choice["options"][0]["label"] == "{G/W}{G/W} bezahlen"
    eng.resolve_pending_choice("pay")
    assert on_battlefield(eng, obj)
    assert all(land.tapped for land in lands)


def test_lands_of_other_colors_cannot_pay():
    eng = engine()
    obj = put(eng, "Arctic Nishoba")
    basic_land(eng, "Island")
    upkeep(eng)
    assert not on_battlefield(eng, obj)
