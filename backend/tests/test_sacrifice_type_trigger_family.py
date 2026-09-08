"""RULE 122.1a/701.17 "Whenever you sacrifice a Food/Clue/Treasure, <effect>."
(Experimental Confectioner/Tireless Tracker/Captain Lannery Storm-shaped) —
a player-subject trigger scoped by the sacrificed permanent's printed type,
closing a gap `_PLAYER_TRIGGER_CONDITIONS`'s bare event-name table couldn't
express (no filter). New pieces: `segmenter._SACRIFICE_TYPE_TRIGGER_RE` +
`effect_binder._trigger_condition`'s `sacrifice_type` predicate, reading
`EventType.SACRIFICE`'s own `object_types` payload the same membership way
`spell_card_types` already checks a cast spell's.

Reference: mtg_analyzer/parser/oracle/segmenter.py, mtg_analyzer/game/
binding/core.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_tireless_tracker_is_modeled():
    card = Card(
        id="Tireless Tracker", name="Tireless Tracker", type_line="Creature — Human Scout",
        is_creature=True, power=3, toughness=2,
        oracle_text=(
            "Landfall — Whenever a land you control enters, investigate. "
            "(Create a Clue token. It's an artifact with \"{2}, Sacrifice this "
            "artifact: Draw a card.\")\n"
            "Whenever you sacrifice a Clue, put a +1/+1 counter on Tireless Tracker."
        ),
    )
    assert parse_oracle(card).modeled is True


def test_sacrifice_food_trigger_fires_and_scopes_by_type():
    eng = _engine()
    state = eng.state
    guest = _bf(state, Card(
        id="Test Rapacious Guest", name="Test Rapacious Guest", type_line="Creature — Halfling",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you sacrifice a Food, put a +1/+1 counter on this creature.",
    ))
    food = _bf(state, Card(id="Food", name="Food", type_line="Artifact — Food", is_land=False))
    treasure = _bf(state, Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure"))

    eng.rules.put_into_graveyard(treasure)
    assert eng.rules.put_triggers_on_stack() == 0  # wrong type — must not fire

    eng.rules.put_into_graveyard(food)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    continuous.recompute(state)

    assert guest.plus_one_counters == 1


def test_sacrifice_trigger_does_not_fire_for_an_opponents_sacrifice():
    eng = _engine()
    state = eng.state
    guest = _bf(state, Card(
        id="Test Rapacious Guest 2", name="Test Rapacious Guest 2", type_line="Creature — Halfling",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you sacrifice a Food, put a +1/+1 counter on this creature.",
    ), controller="p1")
    opp_food = _bf(state, Card(id="Opp Food", name="Opp Food", type_line="Artifact — Food"), controller="p2")

    eng.rules.put_into_graveyard(opp_food)
    assert eng.rules.put_triggers_on_stack() == 0
    continuous.recompute(state)
    assert guest.plus_one_counters == 0
