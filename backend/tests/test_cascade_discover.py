"""Cast / put / draw fire different events; cascade & discover free-cast from
the top of the library (RULE 118.9 / 702.85 / 702.164).

The point under test: a "put onto the battlefield" is a direct zone change
(ENTERS_BATTLEFIELD, no stack, no SPELL_CAST), while a free cast — cascade,
discover, "cast without paying" — is a *real* cast that uses the stack and
fires SPELL_CAST (flagged ``free``). Cascade/discover exile from the top
until a legal hit, may cast it, and bottom the rest in a random order.
"""

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import CascadeEffect, DiscoverEffect, EffectRegistry


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def spell(name, cmc, is_creature=True):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear" if is_creature else "Instant",
        converted_mana_cost=cmc,
        is_creature=is_creature,
        is_instant=not is_creature,
        power=1 if is_creature else None,
        toughness=1 if is_creature else None,
    )


def engine_with_library(cards):
    eng = GameEngine.new_game([("p1", "Alice", list(cards))], starting_hand=0)
    return eng, eng.state.active_player


def events_of(eng):
    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    return seen


# --- Cast vs. put fire different events -------------------------------------


def test_put_onto_battlefield_does_not_use_the_stack_or_fire_cast():
    eng, p1 = engine_with_library([spell("Bear", 2)])
    seen = events_of(eng)
    eng.rules._request_search(p1, "Creature", "battlefield")
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)

    types = [e.type for e in seen]
    assert EventType.ENTERS_BATTLEFIELD in types
    assert EventType.SPELL_CAST not in types  # never cast — no stack
    assert not eng.state.stack


def test_cast_without_paying_uses_the_stack_and_flags_free():
    eng, p1 = engine_with_library([land()])
    bear = GameObject(spell("Bear", 2), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(bear)
    seen = events_of(eng)

    item = eng.rules.cast_without_paying(p1, bear)
    assert item in eng.state.stack  # it went on the stack
    cast_events = [e for e in seen if e.type == EventType.SPELL_CAST]
    assert cast_events and cast_events[0].get("free") is True
    assert p1.mana_pool.total() == 0  # nothing was paid


def test_free_cast_permanent_still_resolves_onto_the_battlefield():
    eng, p1 = engine_with_library([land()])
    bear = GameObject(spell("Bear", 2), owner_id="p1", zone=Zone.HAND)
    p1.hand.append(bear)
    eng.rules.cast_without_paying(p1, bear)
    eng.resolve_until_stable()
    assert bear in eng.state.battlefield


# --- Cascade (RULE 702.85) --------------------------------------------------


def test_cascade_exiles_until_a_cheaper_nonland_then_offers_a_free_cast():
    # top-of-library (list end) revealed first: Land, then a too-expensive
    # creature, then the cheap hit; a filler land stays underneath.
    lib = [land("Filler"), spell("Small", 2), spell("Big", 5), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    small = next(o for o in p1.library if o.name == "Small")

    eng.rules._request_cascade(p1, max_mana_value=4)  # hits mana value <= 3
    choice = eng.state.pending_choice
    assert choice["kind"] == "play_during_resolution"
    assert [eng.state.find_object(i).name for i in choice["instance_ids"]] == ["Small"]
    assert len(p1.exile) == 3  # Land, Big, Small revealed

    eng.play_resolution_card(p1, small)
    assert small.zone == Zone.STACK  # opponents can respond before it resolves
    eng.resolve_until_stable()
    assert small in eng.state.battlefield
    # The non-hits went to the bottom; nothing is left in exile.
    assert not p1.exile
    bottom_names = {p1.library[0].name, p1.library[1].name}
    assert bottom_names == {"TopLand", "Big"}


def test_cascade_declined_bottoms_the_hit_too():
    lib = [land("Filler"), spell("Small", 2), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    eng.rules._request_cascade(p1, max_mana_value=4)
    eng.rules.resolve_choice("decline")  # decline the free cast
    assert eng.state.pending_choice is None
    assert not eng.state.stack
    assert not p1.exile
    assert {o.name for o in p1.library} == {"Filler", "Small", "TopLand"}


def test_cascade_with_no_hit_bottoms_everything_no_choice():
    eng, p1 = engine_with_library([land("A"), land("B")])
    eng.rules._request_cascade(p1, max_mana_value=4)  # only lands — no hit
    assert eng.state.pending_choice is None
    assert not p1.exile
    assert len(p1.library) == 2  # all put back on the bottom


# --- Discover (RULE 702.164) ------------------------------------------------


def test_discover_can_cast_the_hit_for_free():
    lib = [land("Filler"), spell("Small", 3), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    small = next(o for o in p1.library if o.name == "Small")
    eng.rules._request_discover(p1, max_mana_value=3)  # mana value <= 3
    assert eng.state.pending_choice["kind"] == "discover"
    eng.rules.resolve_choice("cast")  # cast
    eng.resolve_until_stable()
    assert small in eng.state.battlefield
    assert not p1.exile


def test_discover_declined_puts_the_hit_into_hand():
    lib = [land("Filler"), spell("Small", 3), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    eng.rules._request_discover(p1, max_mana_value=3)
    eng.rules.resolve_choice("hand")  # "put it into your hand"
    assert any(o.name == "Small" for o in p1.hand)
    assert not eng.state.stack
    assert not p1.exile


# --- Registry + resolve_pending_choice dispatch -----------------------------


def test_cascade_effect_derives_threshold_from_its_source_spell():
    lib = [land("Filler"), spell("Small", 2), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    source = GameObject(spell("Maelstrom", 4, is_creature=False), owner_id="p1", zone=Zone.STACK)
    effect = CascadeEffect(source=source)
    effect.apply(eng.rules.context)
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    assert eng.state.find_object(eng.state.pending_choice["instance_ids"][0]).name == "Small"


def test_registry_builds_cascade_and_discover():
    assert isinstance(EffectRegistry.create("cascade", {}), CascadeEffect)
    assert isinstance(EffectRegistry.create("discover", {"mana_value": 3}), DiscoverEffect)


def test_engine_resolve_pending_choice_routes_cascade():
    lib = [land("Filler"), spell("Small", 2), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    small = next(o for o in p1.library if o.name == "Small")
    eng.rules._request_cascade(p1, max_mana_value=4)
    eng.play_resolution_card(p1, small)
    assert eng.state.pending_choice is None
    assert small.zone == Zone.STACK
    eng.resolve_until_stable()
    assert small in eng.state.battlefield


# --- The choice options (what a popup renders) ------------------------------


def test_cascade_offers_a_cast_action_and_decline():
    lib = [land("Filler"), spell("Small", 2), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    eng.rules._request_cascade(p1, max_mana_value=4)
    actions = eng.resolution_play_actions(p1)
    assert {action["type"] for action in actions} == {"cast_spell", "decline"}
    assert all(action["type"] != "play_land" for action in actions)
    assert eng.state.pending_choice["prompt"]


def test_discover_offers_two_positive_options_not_a_decline():
    lib = [land("Filler"), spell("Small", 3), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    eng.rules._request_discover(p1, max_mana_value=3)
    choice = eng.state.pending_choice
    assert [o["id"] for o in choice["options"]] == ["cast", "hand"]
    assert choice["optional"] is False  # never "nothing"


def test_engine_dispatch_discover_to_hand_and_cast():
    # to_hand path
    lib = [land("Filler"), spell("Small", 3), land("TopLand")]
    eng, p1 = engine_with_library(lib)
    eng.rules._request_discover(p1, max_mana_value=3)
    eng.resolve_pending_choice("hand")
    assert any(o.name == "Small" for o in p1.hand)

    # cast path (fresh game)
    eng2, p2 = engine_with_library(lib)
    small2 = next(o for o in p2.library if o.name == "Small")
    eng2.rules._request_discover(p2, max_mana_value=3)
    eng2.resolve_pending_choice("cast")
    assert small2 in eng2.state.battlefield
