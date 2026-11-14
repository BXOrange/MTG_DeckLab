"""Warp Speed: lands you control enter untapped, tutor on entry, discounted sacrifice-draw-two."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import cast, game, stock_library

NAME = "Warp Speed"
ORACLE = (
    "Lands you control enter untapped.\n"
    "When this enchantment enters, search your library for a basic land card or Planet card, reveal it, put it into "
    "your hand, then shuffle.\n"
    "Strange new worlds — {7}{U}{U}, Sacrifice this enchantment: Draw two cards. This ability costs {X} less to "
    "activate, where X is the number of differently named lands you control."
)
FULL_COST_GENERIC = 7  # the printed {7} before the differently-named-lands discount


def _warp():
    return Card(id="warp", name=NAME, type_line="Enchantment",
                mana_cost_string="{2}{U}", converted_mana_cost=3, oracle_text=ORACLE)


def _tapped_land(name="Tapped Land"):
    return Card(id=name, name=name, type_line="Land", is_land=True, oracle_text=f"{name} enters tapped.")


def _put(engine, card, zone, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        engine.state.add_to_battlefield(obj)
    else:
        engine.state.player_by_id(owner).add_to_zone(obj, zone)
    return obj


def _board(with_warp=True):
    engine, p1, p2 = game()
    warp = _put(engine, _warp(), Zone.BATTLEFIELD) if with_warp else None
    return engine, p1, p2, warp


def test_specs_are_fresh_valid_and_bind():
    first, second = specs_for(_warp()), specs_for(_warp())
    assert first[0] is not second[0] and sorted(s.ability_kind for s in first) == ["activated", "static", "triggered"]
    for spec in first:
        spec.validate()
    obj = _put(game()[0], _warp(), Zone.BATTLEFIELD)
    assert obj.triggered_abilities and obj.activated_abilities and obj.static_effects


def test_own_tapped_land_enters_untapped_but_without_warp_speed_it_enters_tapped():
    engine, p1, p2, warp = _board()
    land = _put(engine, _tapped_land(), Zone.HAND)
    engine.play_land(p1, land)
    assert land.zone == Zone.BATTLEFIELD and not land.tapped

    engine, p1, p2, _ = _board(with_warp=False)
    land = _put(engine, _tapped_land(), Zone.HAND)
    engine.play_land(p1, land)
    assert land.tapped


def test_opponents_lands_still_enter_tapped():
    engine, p1, p2, warp = _board()
    land = _put(engine, _tapped_land(), Zone.HAND, owner="p2")
    engine.state.current_step = "main1"
    engine.state.active_player_index = 1
    engine.play_land(p2, land)
    assert land.tapped


def test_entering_tutors_a_basic_land_or_planet_to_hand():
    engine, p1, p2 = game()
    stock_library(engine, "p1", 3, "Instant")
    basic = _put(engine, Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), Zone.LIBRARY)
    planet = _put(engine, Card(id="P", name="Terra Nova", type_line="Land — Planet", is_land=True), Zone.LIBRARY)
    plain = _put(engine, Card(id="N", name="Plain Nonbasic", type_line="Land", is_land=True), Zone.LIBRARY)
    warp = _put(engine, _warp(), Zone.HAND)
    cast(engine, p1, warp)
    choice = engine.state.pending_choice
    offered = {o.get("instance_id") for o in choice["options"] if "instance_id" in o}
    assert basic.instance_id in offered and planet.instance_id in offered and plain.instance_id not in offered
    engine.resolve_pending_choice(str(basic.instance_id))
    engine.resolve_until_stable()
    assert basic in p1.hand and plain in p1.library


@pytest.mark.parametrize("names,expected_generic", [
    (("Forest", "Forest", "Forest"), FULL_COST_GENERIC - 1),  # one differently named land
    (("Forest", "Island", "Swamp"), FULL_COST_GENERIC - 3),
    ((), FULL_COST_GENERIC),
])
def test_sacrifice_draw_two_costs_x_less_for_differently_named_lands(names, expected_generic):
    engine, p1, p2, warp = _board()
    stock_library(engine, "p1", 4, "Instant")
    for i, name in enumerate(names):
        land = _put(engine, Card(id=f"{name}{i}", name=name, type_line=f"Basic Land — {name}", is_land=True),
                    Zone.BATTLEFIELD)
        land.tapped = True  # only the floating pool may pay, so the exact cost is observable
    engine.recompute_continuous_effects()
    # One mana short must be refused; exactly the discounted cost must pay.
    p1.mana_pool.add_many({"U": 2, "C": expected_generic - 1})
    with pytest.raises(Exception):
        engine.activate_ability(p1, warp, 0)
    assert warp.zone == Zone.BATTLEFIELD and not p1.hand
    p1.mana_pool.add_many({"C": 1})
    engine.activate_ability(p1, warp, 0)
    engine.resolve_until_stable()
    assert warp.zone != Zone.BATTLEFIELD and len(p1.hand) == 2
