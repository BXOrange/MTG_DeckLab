"""Interactive ordering of simultaneous triggers (RULE 603.3b)."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects import TriggeredAbility
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.events import EventType


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _trigger(controller, description):
    return TriggeredAbility(
        trigger_event=EventType.DRAW, effects=[],
        controller_id=controller, description=description,
    )


def test_two_active_player_triggers_prompt_for_order():
    eng = make_engine()
    eng.begin_turn()  # p1 active
    eng.state.interactive_ordering = True
    eng.rules.pending_triggers = [
        (_trigger("p1", "A"), None),
        (_trigger("p1", "B"), None),
    ]
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 0  # nothing placed yet — awaiting the choice
    choice = eng.state.pending_choice
    assert choice["kind"] == "order_triggers"
    assert [o["label"] for o in choice["options"]] == ["A", "B"]
    assert not eng.state.stack

    # Choose to place "B" first (bottom of stack → resolves last).
    eng.rules.resolve_trigger_order_choice(1)
    assert eng.state.pending_choice is None
    descriptions = [item.description for item in eng.state.stack]
    assert descriptions == ["B", "A"]


def test_single_trigger_does_not_prompt():
    eng = make_engine()
    eng.begin_turn()
    eng.state.interactive_ordering = True
    eng.rules.pending_triggers = [(_trigger("p1", "solo"), None)]
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None
    assert [i.description for i in eng.state.stack] == ["solo"]


def test_ordering_off_by_default_places_deterministically():
    eng = make_engine()
    eng.begin_turn()
    # interactive_ordering defaults False.
    eng.rules.pending_triggers = [
        (_trigger("p1", "A"), None),
        (_trigger("p2", "B"), None),
    ]
    eng.rules.put_triggers_on_stack()
    assert eng.state.pending_choice is None
    # Active player's trigger placed first (bottom), opponent's on top.
    assert [i.description for i in eng.state.stack] == ["A", "B"]
