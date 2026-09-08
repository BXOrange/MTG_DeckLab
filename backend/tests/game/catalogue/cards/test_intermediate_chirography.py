"""Intermediate Chirography implements its three Class levels."""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _ic_card():
    return Card(id="ic", name="Intermediate Chirography", type_line="Enchantment — Class",
                oracle_text=("(Gain the next level as a sorcery to add its ability.)\n"
                             "When this Class enters, create a 2/1 white and black Inkling "
                             "creature token with flying.\n{1}{B}: Level 2\nWhenever you "
                             "lose life for the first time each turn, put a +1/+1 counter "
                             "on target creature you control.\n{2}{B}: Level 3\nAt the "
                             "beginning of each end step, if a modified creature died "
                             "under your control this turn, create a 2/1 white and black "
                             "Inkling creature token with flying."))


def test_registered_and_binds():
    assert is_registered("Intermediate Chirography")
    specs = _REGISTRY["intermediate chirography"]()
    assert [s.effects[0].type for s in specs] == [
        "create_token", "class_level", "add_counters", "class_level",
        "intermediate_chirography_l3",
    ]
    src = GameObject(_ic_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_ic_card())


def test_dies_with_a_counter_arms_the_modified_tracker():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    eng.state.fire_event(GameEvent(
        EventType.DIES, instance_id=999, controller_id="p1",
        object_types=["creature"], counters={"+1/+1": 2},
    ))
    assert eng.state.modified_creatures_died_this_turn.get("p1", 0) == 1
    # a counterless death doesn't arm it
    eng.state.fire_event(GameEvent(
        EventType.DIES, instance_id=998, controller_id="p1",
        object_types=["creature"], counters={},
    ))
    assert eng.state.modified_creatures_died_this_turn.get("p1", 0) == 1


def test_l3_effect_gates_on_the_tracker():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_ic_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)

    eng.rules._apply_effect_specs([{"type": "intermediate_chirography_l3", "params": {}}], src)
    assert not [o for o in eng.state.battlefield if o.card.name == "Inkling"]

    eng.state.modified_creatures_died_this_turn["p1"] = 1
    eng.rules._apply_effect_specs([{"type": "intermediate_chirography_l3", "params": {}}], src)
    assert len([o for o in eng.state.battlefield if o.card.name == "Inkling"]) == 1
