"""PAR-274: reveal until land card(s), put onto the battlefield, rest on the bottom in a random order.

U.S.S. Voyager, Lone Wanderer (two lands, tapped), Will Riker, First in the Field (two lands, sacrificed at the
beginning of the next end step) and Janice Rand, Essential Aide (counter on a commander, then one tapped land).
Real cached cards on a real engine.
"""

from __future__ import annotations

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, attack, cast, game, on_battlefield, vanilla


def _lib_card(player_id: str, name: str, land: bool) -> GameObject:
    card = Card(id=name, name=name, type_line="Land" if land else "Sorcery", is_land=land)
    return GameObject(card, owner_id=player_id, zone=Zone.LIBRARY)


def _stack_library(player, spec: list[tuple[str, bool]]) -> dict[str, GameObject]:
    """``spec`` runs top → bottom; the library list keeps its top at the end."""
    objs = [_lib_card(player.id, name, land) for name, land in spec]
    player.library[:] = list(reversed(objs))
    return {o.card.name: o for o in objs}


#: top → bottom: two lands are reached after two nonlands in between; ``Untouched`` is never revealed.
_TWO_LAND_LIBRARY = [("Spell1", False), ("LandA", True), ("Spell2", False), ("LandB", True), ("Untouched", False)]


def _bottom_names(player, count):
    return {o.card.name for o in player.library[:count]}


def test_voyager_puts_both_lands_onto_the_battlefield_tapped_and_bottoms_the_rest():
    engine, p1, p2 = game("U.S.S. Voyager, Lone Wanderer")
    objs = _stack_library(p1, _TWO_LAND_LIBRARY)
    cast(engine, p1, p1.hand[0])
    engine.resolve_until_stable()
    for name in ("LandA", "LandB"):
        assert objs[name].zone == Zone.BATTLEFIELD and objs[name].tapped, name
    assert _bottom_names(p1, 2) == {"Spell1", "Spell2"}
    assert p1.library[-1] is objs["Untouched"]
    assert objs["Untouched"].zone == Zone.LIBRARY


def test_voyager_with_one_land_left_takes_it_and_bottoms_the_rest():
    engine, p1, p2 = game("U.S.S. Voyager, Lone Wanderer")
    objs = _stack_library(p1, [("Spell1", False), ("LandA", True), ("Spell2", False)])
    cast(engine, p1, p1.hand[0])
    engine.resolve_until_stable()
    assert objs["LandA"].zone == Zone.BATTLEFIELD
    assert {o.card.name for o in p1.library} == {"Spell1", "Spell2"}


def test_riker_lands_enter_untapped_and_are_sacrificed_at_the_next_end_step():
    engine, p1, p2 = game(via_steps=True, stop_at="main1")
    on_battlefield(engine, "p1", "Will Riker, First in the Field")
    survivor = GameObject(Card(id="Mine", name="Mine", type_line="Land", is_land=True), owner_id="p1", zone=Zone.BATTLEFIELD)
    survivor.controller_id = "p1"
    engine.state.add_to_battlefield(survivor)
    objs = _stack_library(p1, _TWO_LAND_LIBRARY)
    advance_to(engine, "begin_combat")
    engine.resolve_until_stable()
    for name in ("LandA", "LandB"):
        assert objs[name].zone == Zone.BATTLEFIELD and not objs[name].tapped, name
    assert _bottom_names(p1, 2) == {"Spell1", "Spell2"}
    advance_to(engine, "end")
    engine.resolve_until_stable()
    for name in ("LandA", "LandB"):
        assert objs[name].zone == Zone.GRAVEYARD, name
    # RULE 701.21: only the lands put onto the battlefield this way are sacrificed.
    assert survivor.zone == Zone.BATTLEFIELD


def test_rand_adds_a_counter_to_the_commander_then_puts_one_land_tapped():
    engine, p1, p2 = game(via_steps=True, stop_at="main1")
    on_battlefield(engine, "p1", "Janice Rand, Essential Aide")
    commander = vanilla(engine, "p1", "Commander Bear")
    commander.is_commander = True
    objs = _stack_library(p1, _TWO_LAND_LIBRARY)
    attack(engine, p1, commander)
    assert commander.counters.get("+1/+1", 0) == 1
    assert objs["LandA"].zone == Zone.BATTLEFIELD and objs["LandA"].tapped
    assert objs["LandB"].zone == Zone.LIBRARY
    assert objs["Spell1"] in p1.library
    assert p1.library[0] is objs["Spell1"]


def test_rand_ignores_a_noncommander_attacker():
    engine, p1, p2 = game(via_steps=True, stop_at="main1")
    on_battlefield(engine, "p1", "Janice Rand, Essential Aide")
    bear = vanilla(engine, "p1")
    objs = _stack_library(p1, _TWO_LAND_LIBRARY)
    attack(engine, p1, bear)
    assert objs["LandA"].zone == Zone.LIBRARY and bear.counters.get("+1/+1", 0) == 0
