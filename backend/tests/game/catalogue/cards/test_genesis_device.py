"""Genesis Device: sacrifice any number of lands, then search for up to that many lands onto the battlefield tapped."""
import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import game

NAME = "Genesis Device"
ORACLE = (
    "When Genesis Device enters, search your library for a basic land card or Planet card, put it onto the "
    "battlefield tapped, then shuffle.\n"
    "{3}{G}{G}, {T}, Sacrifice Genesis Device: Sacrifice any number of lands you control, then search your library "
    "for up to that many land cards, put them onto the battlefield tapped, then shuffle. Activate only as a sorcery."
)
ACTIVATION_MANA = {"C": 3, "G": 2}


def _device():
    return Card(id="gd", name=NAME, type_line="Legendary Artifact", is_legendary=True,
                mana_cost_string="{2}{G}", converted_mana_cost=3, oracle_text=ORACLE)


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


def _land(name):
    return Card(id=name, name=name, type_line="Land", is_land=True)


def _board(lands_in_play=3, lands_in_library=5):
    engine, p1, p2 = game()
    device = _put(engine, _device(), Zone.BATTLEFIELD)
    in_play = [_put(engine, _land(f"Field {i}"), Zone.BATTLEFIELD) for i in range(lands_in_play)]
    for land in in_play:
        land.tapped = True  # payment comes from the pool, so every land stays a sacrifice option
    library = [_put(engine, _land(f"Deep {i}"), Zone.LIBRARY) for i in range(lands_in_library)]
    _put(engine, Card(id="spell", name="Not a land", type_line="Instant"), Zone.LIBRARY)
    p1.mana_pool.add_many(ACTIVATION_MANA)
    return engine, p1, p2, device, in_play, library


def _drive(engine, sacrifice, fetch):
    """Answer the pending choices: pick ``sacrifice`` lands one at a time (then stop with "decline"), then fetch
    ``fetch`` (cards from the search, in order). Returns the pending-choice kinds seen."""
    kinds, to_sacrifice, to_fetch = [], list(sacrifice), list(fetch)
    for _ in range(30):
        choice = engine.state.pending_choice
        if not choice:
            break
        kinds.append((choice["kind"], choice.get("action")))
        ids = {o.get("instance_id"): o["id"] for o in choice["options"] if "instance_id" in o}
        if choice["kind"] == "choose_objects" and choice["action"] == "sacrifice":
            answer = str(ids[to_sacrifice.pop(0).instance_id]) if to_sacrifice else "decline"
        elif to_fetch and to_fetch[0].instance_id in ids:
            answer = str(ids[to_fetch.pop(0).instance_id])
        else:
            answer = "decline"
        engine.resolve_pending_choice(answer)
        engine.resolve_until_stable()
    return kinds


def test_specs_are_fresh_valid_and_bind():
    first, second = specs_for(_device()), specs_for(_device())
    assert first[0] is not second[0] and sorted(s.ability_kind for s in first) == ["activated", "triggered"]
    for spec in first:
        spec.validate()
    obj = _put(game()[0], _device(), Zone.BATTLEFIELD)
    assert obj.triggered_abilities and obj.activated_abilities


@pytest.mark.parametrize("clone", [False, True])
def test_sacrifices_chosen_lands_and_fetches_that_many_tapped(clone):
    engine, p1, p2, device, in_play, library = _board()
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    assert device.zone == Zone.GRAVEYARD  # sacrificed as part of the cost
    if clone:
        engine = GameEngine(engine.state.clone())
        p1 = engine.state.player_by_id("p1")
        in_play = [engine.state.find_object(o.instance_id) for o in in_play]
        library = [engine.state.find_object(o.instance_id) for o in library]
    _drive(engine, in_play[:2], library[3:5])
    assert [o.zone for o in in_play] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.BATTLEFIELD]
    fetched = [o for o in library if o.zone == Zone.BATTLEFIELD]
    assert {o.name for o in fetched} == {"Deep 3", "Deep 4"} and all(o.tapped for o in fetched)
    assert len(p1.library) == 4  # 6 cards less the 2 fetched (the nonland stays)


def test_sacrificing_zero_lands_fetches_nothing_but_the_device_is_still_gone():
    engine, p1, p2, device, in_play, library = _board()
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    _drive(engine, [], library)
    assert device.zone == Zone.GRAVEYARD and all(o.zone == Zone.BATTLEFIELD for o in in_play)
    assert all(o.zone == Zone.LIBRARY for o in library)


def test_fetching_is_up_to_that_many_and_may_be_declined_early():
    engine, p1, p2, device, in_play, library = _board()
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    _drive(engine, in_play, library[:1])  # sacrifice three, fetch only one then decline
    assert sum(1 for o in library if o.zone == Zone.BATTLEFIELD) == 1
    assert all(o.zone == Zone.GRAVEYARD for o in in_play)


def test_a_short_library_caps_the_fetch():
    engine, p1, p2, device, in_play, library = _board(lands_in_library=1)
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    _drive(engine, in_play, library)
    assert library[0].zone == Zone.BATTLEFIELD and all(o.zone == Zone.GRAVEYARD for o in in_play)


def test_only_lands_you_control_are_offered_for_sacrifice():
    engine, p1, p2, device, in_play, library = _board(lands_in_play=1)
    _put(engine, Card(id="bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
         Zone.BATTLEFIELD)
    foe_land = _put(engine, _land("Foe Land"), Zone.BATTLEFIELD, owner="p2")
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    offered = {o.get("label") for o in engine.state.pending_choice["options"]}
    assert "Field 0" in offered and "Bear" not in offered and foe_land.name not in offered


def test_search_offers_only_land_cards():
    engine, p1, p2, device, in_play, library = _board(lands_in_play=1)
    engine.activate_ability(p1, device, 0)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(in_play[0].instance_id))  # sacrifice the only land
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "search"
    assert "Not a land" not in {o.get("label") for o in choice["options"]}


def test_activation_is_sorcery_speed_only():
    engine, p1, p2, device, in_play, library = _board()
    engine.state.current_step = "declare_attackers"
    with pytest.raises(Exception):
        engine.activate_ability(p1, device, 0)
    assert device.zone == Zone.BATTLEFIELD


def test_entering_fetches_a_basic_land_or_planet_tapped():
    engine, p1, p2 = game()
    basic = _put(engine, Card(id="F", name="Forest", type_line="Basic Land — Forest", is_land=True), Zone.LIBRARY)
    planet = _put(engine, Card(id="P", name="Terra Nova", type_line="Land — Planet", is_land=True), Zone.LIBRARY)
    plain = _put(engine, _land("Plain Nonbasic"), Zone.LIBRARY)
    obj = _put(engine, _device(), Zone.HAND)
    from tests.support.star_trek import cast
    cast(engine, p1, obj)
    offered = {o.get("instance_id") for o in engine.state.pending_choice["options"]}
    assert basic.instance_id in offered and planet.instance_id in offered and plain.instance_id not in offered
    engine.resolve_pending_choice(str(planet.instance_id))
    engine.resolve_until_stable()
    assert planet.zone == Zone.BATTLEFIELD and planet.tapped
