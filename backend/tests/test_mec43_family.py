"""MEC-43 — `cEDH staples 2`'s undiagnosed remainder, first batch: 9
near-free reuses of primitives shipped for entirely different cards
(Contamination, Leveler, Natural Order, Magda Brazen Outlaw, Unmarked
Grave, Unsubstantiate, Starting Town, Teferi Master of Time, March of
Otherworldly Light).

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _vanilla(name="Bear", power=2, toughness=2, is_land=False, mana_cost_string="{1}{G}", color_identity=None):
    if is_land:
        return Card(id=name, name=name, type_line="Land", is_land=True, oracle_text="{T}: Add {C}.")
    return Card(
        id=name, name=name, type_line="Creature — Bear", is_creature=True,
        power=power, toughness=toughness, mana_cost_string=mana_cost_string,
        converted_mana_cost=2, color_identity=color_identity,
    )


def _filler(n):
    return [_vanilla(f"Filler {i}") for i in range(n)]


def _put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).hand.append(obj)
    return obj


def _to_graveyard(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    bind_from_catalogue(obj)
    state.player_by_id(controller).graveyard.append(obj)
    return obj


def _fire_etb(state, obj):
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            controller_id=obj.controller_id,
            object=obj.name,
            instance_id=obj.instance_id,
            object_types=sorted(obj.type_words),
        )
    )


# ---------------------------------------------------------------------------
# Contamination
# ---------------------------------------------------------------------------


def test_contamination_overrides_land_mana_to_black():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    _put(state, _named("Contamination"))
    land = _put(state, _vanilla("Land", is_land=True))
    eng.recompute_continuous_effects()

    eng.tap_for_mana(p1, land)
    assert p1.mana_pool.pool.get("B", 0) == 1
    assert not p1.mana_pool.pool.get("C")


# ---------------------------------------------------------------------------
# Leveler
# ---------------------------------------------------------------------------


def test_leveler_etb_exiles_whole_library():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    leveler = _put(state, _named("Leveler"))
    _fire_etb(state, leveler)
    eng.resolve_until_stable()

    assert not p1.library
    assert len(p1.exile) == 5


# ---------------------------------------------------------------------------
# Natural Order
# ---------------------------------------------------------------------------


def test_natural_order_sacrifices_green_creature_and_finds_one():
    eng = make_engine(_filler(3), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    order = _to_hand(state, _named("Natural Order"))
    green_creature = _put(state, _vanilla("Green Guy", color_identity={"G"}))
    library_green = _vanilla("Library Green", color_identity={"G"})
    state.player_by_id("p1").library.append(
        GameObject(library_green, owner_id="p1", zone=Zone.LIBRARY)
    )
    p1.mana_pool.add_many({"G": 2, "C": 2})
    eng.recompute_continuous_effects()

    eng.begin_turn()
    state.current_step = "main1"
    assert eng.can_cast(p1, order)  # a green creature is available to sacrifice
    eng.cast_spell(p1, order)
    eng.resolve_until_stable()

    assert green_creature not in state.battlefield
    choice = state.pending_choice
    assert choice is not None and choice.get("kind") == "search"
    picked = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(picked)
    assert any(o.name == "Library Green" for o in state.battlefield)


# ---------------------------------------------------------------------------
# Magda, Brazen Outlaw
# ---------------------------------------------------------------------------


def test_magda_anthem_excludes_herself_but_buffs_other_dwarves():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    magda = _put(state, _named("Magda, Brazen Outlaw"))
    other_dwarf = _put(state, Card(
        id="Other Dwarf", name="Other Dwarf", type_line="Creature — Dwarf",
        is_creature=True, power=1, toughness=1, mana_cost_string="{R}", converted_mana_cost=1,
    ))
    eng.recompute_continuous_effects()

    assert other_dwarf.power == 2  # +1/+0 anthem
    assert magda.power == magda.card.power  # "other" excludes Magda herself


def test_magda_tap_trigger_creates_treasure():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    _put(state, _named("Magda, Brazen Outlaw"))
    other_dwarf = _put(state, Card(
        id="Other Dwarf", name="Other Dwarf", type_line="Creature — Dwarf",
        is_creature=True, power=1, toughness=1, mana_cost_string="{R}", converted_mana_cost=1,
    ))
    eng.recompute_continuous_effects()

    eng.rules.set_tapped(other_dwarf, True)
    eng.resolve_until_stable()

    assert any(o.name == "Treasure" for o in state.battlefield)


def test_magda_sacrifice_five_treasures_finds_artifact_or_dragon():
    eng = make_engine(_filler(3), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    magda = _put(state, _named("Magda, Brazen Outlaw"))
    treasure_card = Card(
        id="Treasure", name="Treasure", type_line="Artifact — Treasure",
        mana_cost_string="", converted_mana_cost=0,
    )
    for _ in range(5):
        _put(state, treasure_card)
    library_dragon = Card(
        id="Dragon", name="Dragon", type_line="Creature — Dragon", is_creature=True,
        power=4, toughness=4, mana_cost_string="{4}{R}", converted_mana_cost=5,
    )
    state.player_by_id("p1").library.append(
        GameObject(library_dragon, owner_id="p1", zone=Zone.LIBRARY)
    )

    ability_idx = 0
    ability = magda.activated_abilities[ability_idx]
    assert eng.can_activate(p1, magda, ability)
    eng.activate_ability(p1, magda, ability_idx)
    eng.resolve_until_stable()
    if state.pending_choice and state.pending_choice.get("kind") == "search":
        picked = state.pending_choice["eligible"][0]["instance_id"]
        eng.rules.resolve_choice(picked)

    treasures_left = [o for o in state.battlefield if o.name == "Treasure"]
    assert len(treasures_left) == 0
    assert any(o.name == "Dragon" for o in state.battlefield)


# ---------------------------------------------------------------------------
# Unmarked Grave
# ---------------------------------------------------------------------------


def test_unmarked_grave_finds_nonlegendary_card_only():
    eng = make_engine(_filler(3), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    grave = _to_hand(state, _named("Unmarked Grave"))
    legendary = Card(
        id="Legend", name="Legend", type_line="Legendary Creature — Human",
        is_creature=True, is_legendary=True, power=1, toughness=1,
        mana_cost_string="{1}", converted_mana_cost=1,
    )
    nonlegendary = _vanilla("Nonlegend")
    state.player_by_id("p1").library.append(GameObject(legendary, owner_id="p1", zone=Zone.LIBRARY))
    state.player_by_id("p1").library.append(GameObject(nonlegendary, owner_id="p1", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"B": 1, "C": 1})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, grave)
    eng.resolve_until_stable()

    choice = state.pending_choice
    names = {e["name"] for e in choice["eligible"]}
    assert "Nonlegend" in names
    assert "Legend" not in names


# ---------------------------------------------------------------------------
# Unsubstantiate
# ---------------------------------------------------------------------------


def test_unsubstantiate_bounces_a_spell_off_the_stack():
    eng = make_engine(_filler(3), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    unsub = _to_hand(state, _named("Unsubstantiate"))
    bolt_like = _to_hand(state, _vanilla("Creature Spell"))

    eng.begin_turn()
    state.current_step = "main1"
    p1.mana_pool.add_many({"G": 1, "C": 1})
    eng.cast_spell(p1, bolt_like)
    assert len(state.stack) == 1

    p1.mana_pool.add_many({"U": 1, "C": 1})
    eng.cast_spell(p1, unsub, targets=[state.stack[0].obj])
    assert len(state.stack) == 2
    eng.rules.resolve_top_of_stack()  # resolve Unsubstantiate
    assert len(state.stack) == 0
    assert any(o.name == "Creature Spell" for o in p1.hand)


def test_unsubstantiate_bounces_a_creature_too():
    eng = make_engine(_filler(3), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    unsub = _to_hand(state, _named("Unsubstantiate"))
    creature = _put(state, _vanilla("Target Creature"))
    p1.mana_pool.add_many({"U": 1, "C": 1})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, unsub, targets=[creature])
    eng.resolve_until_stable()

    assert creature in p1.hand
    assert creature not in state.battlefield


# ---------------------------------------------------------------------------
# Teferi, Master of Time
# ---------------------------------------------------------------------------


def test_teferi_master_of_time_can_activate_at_instant_speed_off_turn():
    eng = make_engine(_filler(5), _filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    teferi = _put(state, _named("Teferi, Master of Time"))
    eng.begin_turn()  # p1's turn starts
    state.active_player_index = state.players.index(state.player_by_id("p2"))
    state.current_step = "main1"

    idx = next(i for i, a in enumerate(teferi.activated_abilities) if a.cost.loyalty == 1)
    ability = teferi.activated_abilities[idx]
    # Neither p1's own turn nor an empty stack — an ordinary sorcery-speed
    # loyalty ability would refuse both; Teferi's own instant-speed grant
    # (conditional_flash={"unconditional": True}) should bypass them.
    assert eng.can_activate(p1, teferi, ability)


def test_teferi_master_of_time_minus_ten_queues_two_extra_turns():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    teferi = _put(state, _named("Teferi, Master of Time"))
    teferi.counters["loyalty"] = 10
    idx = next(i for i, a in enumerate(teferi.activated_abilities) if a.cost.loyalty == -10)

    eng.begin_turn()
    state.current_step = "main1"
    eng.activate_ability(p1, teferi, idx)
    eng.resolve_until_stable()

    assert len(state.extra_turns) == 2


# ---------------------------------------------------------------------------
# March of Otherworldly Light
# ---------------------------------------------------------------------------


def test_march_of_otherworldly_light_exiles_target_with_mv_at_most_x():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    march = _to_hand(state, _named("March of Otherworldly Light"))
    cheap = _put(state, Card(
        id="Cheap", name="Cheap", type_line="Artifact",
        mana_cost_string="{1}", converted_mana_cost=1,
    ))
    p1.mana_pool.add_many({"W": 1, "C": 2})

    eng.begin_turn()
    state.current_step = "main1"
    eng.cast_spell(p1, march, targets=[cheap], x=2)
    eng.resolve_until_stable()

    assert cheap not in state.battlefield
    assert cheap.zone == Zone.EXILE


# ---------------------------------------------------------------------------
# Starting Town
# ---------------------------------------------------------------------------


def test_starting_town_enters_untapped_on_early_turns_only():
    eng = make_engine(_filler(5), hand=0)
    state = eng.state
    p1 = state.player_by_id("p1")
    town = _to_hand(state, _named("Starting Town"))
    state.turn_nr = 2

    eng.begin_turn()
    state.current_step = "main1"
    eng.play_land(p1, town)
    assert town.tapped is False

    town2 = _to_hand(state, _named("Starting Town"))
    p1.lands_played_this_turn = 0
    state.turn_nr = 5
    eng.play_land(p1, town2)
    assert town2.tapped is True
