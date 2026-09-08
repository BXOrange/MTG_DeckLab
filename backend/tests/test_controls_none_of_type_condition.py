""""If you don't control a Food, <effect>." (Butterbur, Bree Innkeeper-shaped
"keep a permanent type replenished" upkeep/end-step payoffs) —
`ConditionalEffect`'s new `controls_none_of_type` key, the mirror image of
`life_gained_this_turn_at_least`/`is_ring_bearer` (same "wrap the rest, tag
the condition" idiom, `segmenter._CONTROLS_NONE_OF_TYPE_CONDITION_RE`).

Reference: mtg_analyzer/parser/oracle/segmenter.py, mtg_analyzer/game/effects/core.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
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


_BUTTERBUR_TEXT = (
    "At the beginning of your end step, if you don't control a Food, "
    "create a Food token."
)


def test_butterbur_is_modeled():
    card = Card(id="Butterbur, Bree Innkeeper", name="Butterbur, Bree Innkeeper",
                type_line="Legendary Creature — Human Peasant", is_creature=True,
                power=2, toughness=2, oracle_text=_BUTTERBUR_TEXT)
    assert parse_oracle(card).modeled is True


def _end_step(obj):
    return GameEvent(EventType.STEP_BEGIN, step="end", instance_id=obj.instance_id)


def test_creates_a_food_when_none_is_controlled():
    eng = _engine()
    state = eng.state
    innkeeper = _bf(state, Card(id="Test Butterbur", name="Test Butterbur",
                                 type_line="Creature — Human", is_creature=True,
                                 power=2, toughness=2, oracle_text=_BUTTERBUR_TEXT))

    state.fire_event(_end_step(innkeeper))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert any(o.name == "Food" for o in state.battlefield)


def test_does_not_create_a_food_when_one_is_already_controlled():
    eng = _engine()
    state = eng.state
    innkeeper = _bf(state, Card(id="Test Butterbur 2", name="Test Butterbur 2",
                                 type_line="Creature — Human", is_creature=True,
                                 power=2, toughness=2, oracle_text=_BUTTERBUR_TEXT))
    _bf(state, Card(id="Existing Food", name="Existing Food", type_line="Artifact — Food"))

    state.fire_event(_end_step(innkeeper))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert sum(1 for o in state.battlefield if "food" in o.card.type_line.lower()) == 1
