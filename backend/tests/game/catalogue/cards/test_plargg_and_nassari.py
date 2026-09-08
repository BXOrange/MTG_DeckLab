"""Plargg and Nassari reveals cards and grants temporary casting permission."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _pn_card():
    return Card(id="pn", name="Plargg and Nassari",
                type_line="Legendary Creature — Orc Efreet", is_creature=True,
                power=5, toughness=4,
                oracle_text=("At the beginning of your upkeep, each player exiles cards "
                             "from the top of their library until they exile a nonland "
                             "card. An opponent chooses a nonland card exiled this way. "
                             "You may cast up to two spells from among the other cards "
                             "exiled this way without paying their mana costs."))


def test_registered_and_binds():
    assert is_registered("Plargg and Nassari")
    spec = _REGISTRY["plargg and nassari"]()[0]
    spec.validate()
    assert spec.effects[0].type == "plargg_and_nassari"
    src = GameObject(_pn_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_pn_card())


def _stock(player, spec):
    # spec: list of (name, is_land, mv) top-last
    for name, is_land, mv in spec:
        c = Card(id=name, name=name,
                 type_line="Basic Land — Forest" if is_land else "Sorcery",
                 is_land=is_land, is_sorcery=not is_land, converted_mana_cost=mv)
        player.add_to_zone(GameObject(c, owner_id=player.id, zone=Zone.LIBRARY),
                           Zone.LIBRARY)


def test_each_player_digs_to_a_nonland_and_two_get_free_casts():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cara", [])],
        starting_life=20, starting_hand=0,
    )
    # p1: land, land, then a nonland MV 2 (on top)
    _stock(eng.state.player_by_id("p1"), [("p1big", False, 6), ("p1l2", True, 0),
                                          ("p1l1", True, 0), ("p1nl", False, 2)])
    _stock(eng.state.player_by_id("p2"), [("p2nl", False, 4)])
    _stock(eng.state.player_by_id("p3"), [("p3nl", False, 1)])

    src = GameObject(_pn_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "plargg_and_nassari", "params": {}}], src)
    eng.resolve_until_stable()

    # nonlands exiled: p1nl(2), p2nl(4), p3nl(1). Denied = p2nl (highest MV).
    # Free-cast granted for the other two: p1nl, p3nl.
    granted = eng.state.free_cast_instance_ids
    by_name = {o.card.name: o for pl in eng.state.players for o in pl.exile}
    assert by_name["p2nl"].instance_id not in granted
    assert by_name["p1nl"].instance_id in granted
    assert by_name["p3nl"].instance_id in granted
