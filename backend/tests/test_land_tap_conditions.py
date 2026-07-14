"""Engine-side behaviour tests for the RULE 614.1 tapped-entry kinds the
oracle-text front-end (`parser/oracle/catalogue/lands.py`) newly claims:
Commander "Battlebond" lands (``unless_opponents``) and the basic-land-
counting fast/slow-land variant (``unless_count`` with ``basic: True``).
The pre-existing kinds (always/pay_life/unless_types/unless_count) are
already covered by `test_ability_catalogue.py`.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.game_session import build_goldfish_engine


def battlebond_land():
    return Card(
        id="BP", name="Bountiful Promenade", type_line="Land", is_land=True,
        oracle_text="This land enters tapped unless you have two or more opponents.\n"
                    "{T}: Add {W} or {G}.",
    )


def basic_count_land():
    return Card(
        id="HBL", name="Hypothetical Basic-Counting Land", type_line="Land", is_land=True,
        oracle_text="This land enters tapped unless you control two or more basic lands.\n"
                    "{T}: Add {B} or {G}.",
    )


def basic_land(subtype):
    return Card(id=subtype, name=subtype, type_line=f"Basic Land — {subtype}",
                is_land=True, oracle_text="({T}: Add mana.)")


def nonbasic_land(name):
    return Card(id=name, name=name, type_line="Land", is_land=True,
                oracle_text="({T}: Add one mana of any color.)")


# ---------------------------------------------------------------------------
# unless_opponents (Battlebond lands)
# ---------------------------------------------------------------------------


def test_battlebond_land_tapped_with_no_opponents():
    # Solo goldfish, no dummy: zero opponents < 2.
    engine = build_goldfish_engine([battlebond_land()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is True


def test_battlebond_land_tapped_with_one_opponent():
    # A solo goldfish's single dummy opponent still isn't "two or more".
    engine = build_goldfish_engine([battlebond_land()], starting_hand=1, with_dummy=True)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is True


def test_battlebond_land_untapped_with_two_or_more_opponents():
    p1 = Player(id="p1", name="You")
    p2 = Player(id="p2", name="Opp1")
    p3 = Player(id="p3", name="Opp2")
    land_obj = GameObject(battlebond_land(), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(land_obj)
    state = GameState(players=[p1, p2, p3])
    engine = GameEngine(state)
    engine.rules.enter_land_tapped(land_obj)
    assert land_obj.tapped is False


def test_battlebond_land_tapped_with_exactly_one_opponent_multiplayer():
    p1 = Player(id="p1", name="You")
    p2 = Player(id="p2", name="Opp1")
    land_obj = GameObject(battlebond_land(), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(land_obj)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    engine.rules.enter_land_tapped(land_obj)
    assert land_obj.tapped is True


# ---------------------------------------------------------------------------
# unless_count with basic=True (counts only basic lands, not any land)
# ---------------------------------------------------------------------------


def test_basic_count_land_untapped_with_two_basic_lands():
    engine = build_goldfish_engine([basic_count_land()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    for subtype in ("Forest", "Plains"):
        engine.state.add_to_battlefield(
            GameObject(basic_land(subtype), owner_id=p1.id, zone=Zone.BATTLEFIELD)
        )
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is False  # two basic lands >= 2


def test_basic_count_land_tapped_with_nonbasic_lands_only():
    engine = build_goldfish_engine([basic_count_land()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    # Two *nonbasic* lands don't count toward the basic-land total, even
    # though `unless_count` (without `basic`) would have been satisfied.
    for name in ("Command Tower", "Reflecting Pool"):
        engine.state.add_to_battlefield(
            GameObject(nonbasic_land(name), owner_id=p1.id, zone=Zone.BATTLEFIELD)
        )
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is True


def test_basic_count_land_tapped_with_zero_basic_lands():
    engine = build_goldfish_engine([basic_count_land()], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.active_player
    land = p1.hand[0]
    engine.play_land(p1, land)
    assert land.tapped is True
