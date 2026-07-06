"""Tests for Player / GameObject / GameState models.

Reference: docs/02_MVP_USECASES_REVISED.md R1.3, mtg_analyzer/models/.
"""

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState, StackItem
from mtg_analyzer.models.player import DEFAULT_STARTING_LIFE, Player


def make_card(name="Grizzly Bears", **kw):
    defaults = dict(
        id=name,
        name=name,
        type_line="Creature — Bear",
        is_creature=True,
        power=2,
        toughness=2,
    )
    defaults.update(kw)
    return Card(**defaults)


def test_game_object_unique_instance_ids():
    card = make_card()
    a = GameObject(card, owner_id="p1")
    b = GameObject(card, owner_id="p1")
    assert a.instance_id != b.instance_id
    # Controller defaults to owner (RULE 108.4).
    assert a.controller_id == "p1"


def test_game_object_counters_affect_power_toughness():
    obj = GameObject(make_card(power=2, toughness=2), owner_id="p1")
    obj.plus_one_counters = 1
    assert obj.power == 3
    assert obj.toughness == 3


def test_game_object_tap_untap():
    obj = GameObject(make_card(), owner_id="p1")
    assert not obj.tapped
    obj.tap()
    assert obj.tapped
    obj.untap()
    assert not obj.tapped


def test_player_defaults_to_commander_life():
    player = Player(id="p1")
    assert player.life == DEFAULT_STARTING_LIFE == 40


def test_player_draw_moves_top_of_library_to_hand():
    player = Player(id="p1")
    for i in range(3):
        obj = GameObject(make_card(name=f"c{i}"), owner_id="p1", zone=Zone.LIBRARY)
        player.library.append(obj)
    top = player.library[-1]
    drawn = player.draw(1)
    assert drawn == [top]
    assert top in player.hand
    assert top.zone == Zone.HAND
    assert len(player.library) == 2


def test_player_draw_from_empty_returns_fewer():
    player = Player(id="p1")
    assert player.draw(3) == []


def test_game_state_requires_players():
    import pytest

    with pytest.raises(ValueError):
        GameState(players=[])


def test_game_state_active_and_lookup():
    p1, p2 = Player(id="p1"), Player(id="p2")
    state = GameState(players=[p1, p2])
    assert state.active_player is p1
    assert state.player_by_id("p2") is p2
    assert state.non_active_players() == [p2]


def test_game_state_event_bus_records_and_notifies():
    state = GameState(players=[Player(id="p1")])
    seen = []
    state.subscribe(seen.append)
    event = GameEvent(EventType.DRAW, player_id="p1", count=1)
    state.fire_event(event)
    assert state.event_log == [event]
    assert seen == [event]


def test_game_state_to_dict_is_serializable():
    import json

    p1 = Player(id="p1", name="Alice")
    state = GameState(players=[p1])
    state.stack.append(StackItem(kind="spell", controller_id="p1", description="Bolt"))
    # Must be JSON-serializable for the WebSocket wire protocol.
    json.dumps(state.to_dict())


def test_stack_item_category_defaults_to_spell():
    item = StackItem(kind="spell", controller_id="p1", description="Bolt")
    assert item.category == "spell"
    assert item.to_dict()["category"] == "spell"


def test_stack_item_ability_defaults_to_triggered():
    # An ability with no recognizable effect object is the triggered path.
    item = StackItem(kind="ability", controller_id="p1", description="draw a card")
    assert item.category == "triggered_ability"


def test_stack_item_category_derived_from_effect_class():
    class ActivatedAbility:  # name-matched, no game/ import needed
        pass

    class TriggeredAbility:
        pass

    activated = StackItem(kind="ability", controller_id="p1", effects=[ActivatedAbility()])
    triggered = StackItem(kind="ability", controller_id="p1", effects=[TriggeredAbility()])
    assert activated.category == "activated_ability"
    assert triggered.category == "triggered_ability"


def test_stack_item_explicit_category_wins():
    item = StackItem(kind="ability", controller_id="p1", category="activated_ability")
    assert item.category == "activated_ability"


def test_stack_item_spell_exposes_type_line():
    obj = GameObject(make_card(), owner_id="p1")
    item = StackItem(kind="spell", controller_id="p1", obj=obj)
    assert item.to_dict()["type_line"] == obj.card.type_line


def test_battlefield_membership_by_controller():
    p1 = Player(id="p1")
    state = GameState(players=[p1])
    obj = GameObject(make_card(), owner_id="p1")
    state.add_to_battlefield(obj)
    assert obj.zone == Zone.BATTLEFIELD
    assert state.permanents_controlled_by("p1") == [obj]
