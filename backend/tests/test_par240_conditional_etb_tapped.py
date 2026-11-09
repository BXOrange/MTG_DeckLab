"""PAR-240: "If you control two or more other lands, this land enters tapped."

Real Oracle text, played through `GameEngine.play_land` (the real RULE 305.1 /
614.1 path). Rulings 2021-07-23: lands entering at the same time are not
considered, and "other" never includes the entering land.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.lands import tap_clause_condition
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.game_session import build_goldfish_engine

ENTRY = "If you control two or more other lands, this land enters tapped.\n"
LANDS = {
    "Cave of the Frost Dragon": ENTRY + "{T}: Add {W}.\n{4}{W}: This land becomes a 3/4 white Dragon creature with flying until end of turn. It's still a land.",
    "Den of the Bugbear": ENTRY + '{T}: Add {R}.\n{3}{R}: Until end of turn, this land becomes a 3/2 red Goblin creature with "Whenever this creature attacks, create a 1/1 red Goblin creature token that\'s tapped and attacking." It\'s still a land.',
    "Hall of Storm Giants": ENTRY + "{T}: Add {U}.\n{5}{U}: Until end of turn, this land becomes a 7/7 blue Giant creature with ward {3}. It's still a land. (Whenever it becomes the target of a spell or ability an opponent controls, counter it unless that player pays {3}.)",
    "Lair of the Hydra": ENTRY + "{T}: Add {G}.\n{X}{G}: Until end of turn, this land becomes an X/X green Hydra creature. It's still a land. X can't be 0.",
}


def _card(name: str) -> Card:
    return Card(id=name, name=name, type_line="Land", is_land=True, oracle_text=LANDS[name])


def _basic() -> Card:
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True,
                oracle_text="({T}: Add {G}.)")


def _on_battlefield(engine, player_id: str, count: int) -> None:
    for _ in range(count):
        engine.state.add_to_battlefield(GameObject(_basic(), owner_id=player_id, zone=Zone.BATTLEFIELD))


def _play(name: str, mine: int, theirs: int = 0) -> GameObject:
    engine = build_goldfish_engine([_card(name)], starting_hand=1, with_dummy=True)
    engine.begin_turn()
    engine.state.current_step = "main1"
    me = engine.state.active_player
    opp = next(p for p in engine.state.players if p.id != me.id)
    _on_battlefield(engine, me.id, mine)
    _on_battlefield(engine, opp.id, theirs)
    land = me.hand[0]
    engine.play_land(me, land)
    assert land.zone == Zone.BATTLEFIELD
    return land


@pytest.mark.parametrize("name", sorted(LANDS))
def test_real_cards_are_modeled(name):
    assert parse_oracle(_card(name)).modeled


@pytest.mark.parametrize("name", sorted(LANDS))
def test_exactly_at_threshold_enters_tapped(name):
    assert _play(name, mine=2).tapped is True


@pytest.mark.parametrize("name", sorted(LANDS))
def test_one_below_threshold_enters_untapped(name):
    assert _play(name, mine=1).tapped is False


@pytest.mark.parametrize("name", sorted(LANDS))
def test_above_threshold_enters_tapped(name):
    assert _play(name, mine=5).tapped is True


@pytest.mark.parametrize("name", sorted(LANDS))
def test_opponents_lands_are_not_counted(name):
    assert _play(name, mine=1, theirs=6).tapped is False


def test_entering_land_does_not_count_itself():
    # First land of the game: 0 other lands. If the entering land counted
    # itself the count would still be < 2, so also check the boundary: one
    # other land + the entering one is 2 lands total but only 1 "other".
    assert _play("Cave of the Frost Dragon", mine=0).tapped is False
    assert _play("Cave of the Frost Dragon", mine=1).tapped is False


def test_prediction_matches_the_real_entry():
    for mine, expected in ((1, False), (2, True)):
        engine = build_goldfish_engine([_card("Lair of the Hydra")], starting_hand=1, with_dummy=True)
        engine.begin_turn()
        engine.state.current_step = "main1"
        me = engine.state.active_player
        _on_battlefield(engine, me.id, mine)
        land = me.hand[0]
        assert engine.rules.predict_land_tapped(land) is expected
        action = next(a for a in engine.legal_actions(me) if a["type"] == "play_land")
        assert action["enters_tapped"] is expected


def test_entering_object_already_on_battlefield_is_not_counted():
    # Direct guard on the count itself: the land being resolved is excluded
    # even if the caller has it on the battlefield already.
    engine = build_goldfish_engine([_card("Cave of the Frost Dragon")], starting_hand=1)
    engine.begin_turn()
    me = engine.state.active_player
    _on_battlefield(engine, me.id, 1)
    land = me.hand[0]
    me.hand.remove(land)
    engine.state.add_to_battlefield(land)
    engine.rules.enter_land_tapped(land)
    assert land.tapped is False  # 1 other land, itself excluded


@pytest.mark.parametrize("line, expected", [
    ("if you control 2 or more other lands, ~ enters tapped.", {"kind": "unless_count", "cmp": "le", "count": 1}),
    ("if you control 3 or fewer other lands, ~ enters tapped.", {"kind": "unless_count", "cmp": "ge", "count": 4}),
    ("if you control 2 or more other lands, this land enters tapped.", {"kind": "unless_count", "cmp": "le", "count": 1}),
])
def test_clause_shape(line, expected):
    assert tap_clause_condition(line) == expected


def test_hive_of_the_eye_tyrant_stays_unmodeled_on_its_other_clause():
    hive = Card(
        id="Hive", name="Hive of the Eye Tyrant", type_line="Land", is_land=True,
        oracle_text=ENTRY + '{T}: Add {B}.\n{3}{B}: Until end of turn, this land becomes a 3/3 black Beholder creature with menace and "Whenever this creature attacks, exile target card from defending player\'s graveyard." It\'s still a land.',
    )
    result = parse_oracle(hive)
    assert not result.modeled
    assert not any("enters tapped" in c for c in result.unclaimed)


def _animated(name: str, x: int = 0) -> GameObject:
    engine = build_goldfish_engine([_card(name)], starting_hand=1, with_dummy=True)
    engine.begin_turn()
    engine.state.current_step = "main1"
    me = engine.state.active_player
    land = me.hand[0]
    me.hand.remove(land)
    engine.state.add_to_battlefield(land)
    land.tapped = False
    land.summoning_sick = False
    _on_battlefield(engine, me.id, 8)
    for o in engine.state.battlefield:
        o.tapped = False
    engine.activate_ability(me, land, 0, **({"x": x} if x else {}))
    while engine.state.stack:
        engine.rules.resolve_top_of_stack()
    engine.recompute_continuous_effects()
    return land


@pytest.mark.parametrize("name, power, toughness", [
    ("Cave of the Frost Dragon", 3, 4), ("Den of the Bugbear", 3, 2), ("Hall of Storm Giants", 7, 7),
])
def test_animation_clause_makes_a_creature_land(name, power, toughness):
    land = _animated(name)
    assert land.is_creature and land.is_land and (land.power, land.toughness) == (power, toughness)


def test_animation_keyword_and_trigger_grants():
    assert "flying" in _animated("Cave of the Frost Dragon").granted_keywords
    assert _animated("Hall of Storm Giants").granted_ward_cost == "{3}"
    assert len(_animated("Den of the Bugbear")._granted_triggered_abilities) == 1


def test_lair_of_the_hydra_x_sets_size_and_x_cannot_be_zero():
    land = _animated("Lair of the Hydra", x=3)
    assert (land.power, land.toughness) == (3, 3)
    with pytest.raises(ValueError):
        _animated("Lair of the Hydra", x=0)
