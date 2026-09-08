"""Interactive ordering of simultaneous triggers (RULE 603.3b)."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import DestroyEffect, TriggeredAbility
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.events import EventType


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _trigger(controller, description, optional=False):
    return TriggeredAbility(
        trigger_event=EventType.DRAW, effects=[],
        controller_id=controller, description=description, optional=optional,
    )


def creature(name, power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _destroy_trigger(source, description, optional=False):
    return TriggeredAbility(
        trigger_event=EventType.DRAW,
        effects=[DestroyEffect(source=source)],
        controller_id=source.controller_id,
        source=source,
        optional=optional,
        description=description,
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


def test_ordering_a_targeted_trigger_pauses_for_its_own_target():
    """ENG-4: picking a targeted trigger via the RULE 603.3b order choice
    must pause for that trigger's own target instead of placing it blind."""
    eng = make_engine()
    eng.begin_turn()
    eng.state.interactive_ordering = True
    victim = put(eng.state, creature("Victim"))
    source = put(eng.state, creature("Source"))

    plain = _trigger("p1", "plain")
    targeted = _destroy_trigger(source, "destroy target permanent")
    eng.rules.pending_triggers = [(plain, None), (targeted, None)]
    eng.rules.put_triggers_on_stack()
    order_choice = eng.state.pending_choice
    assert order_choice["kind"] == "order_triggers"
    targeted_option = next(
        o for o in order_choice["options"] if o["label"] == "destroy target permanent"
    )

    # Place the targeted trigger first — it must pause for its target
    # rather than going on the stack with no target at all.
    eng.rules.resolve_trigger_order_choice(int(targeted_option["id"]))
    target_choice = eng.state.pending_choice
    assert target_choice is not None
    assert target_choice["kind"] == "trigger_target"
    assert not eng.state.stack  # not placed yet

    victim_option = next(
        o for o in target_choice["options"] if o.get("instance_id") == victim.instance_id
    )
    eng.rules.resolve_trigger_target_choice(victim_option["id"])

    # Both triggers are now placed, targeted one first (bottom of stack).
    assert eng.state.pending_choice is None
    descriptions = [item.description for item in eng.state.stack]
    assert descriptions == ["destroy target permanent", "plain"]
    placed_item = eng.state.stack[0]
    assert placed_item.targets == [victim]


def test_ordering_an_optional_trigger_pauses_for_you_may():
    """ENG-4: an optional ("you may") trigger chosen via the order choice
    still asks whether to do it at all, instead of auto-placing."""
    eng = make_engine()
    eng.begin_turn()
    eng.state.interactive_ordering = True

    plain = _trigger("p1", "plain")
    optional = _trigger("p1", "you may draw a card", optional=True)
    eng.rules.pending_triggers = [(plain, None), (optional, None)]
    eng.rules.put_triggers_on_stack()
    order_choice = eng.state.pending_choice
    optional_option = next(
        o for o in order_choice["options"]
        if o["label"] == "you may draw a card"
    )

    eng.rules.resolve_trigger_order_choice(int(optional_option["id"]))
    # No targeting effect at all (RULE 603.5) — still asks do/decline.
    may_choice = eng.state.pending_choice
    assert may_choice is not None
    assert may_choice["kind"] == "trigger_target"
    assert {o["id"] for o in may_choice["options"]} == {"do", "decline"}
    assert not eng.state.stack

    eng.rules.resolve_trigger_target_choice("decline")
    # Declined — only the plain trigger ends up on the stack.
    assert eng.state.pending_choice is None
    assert [i.description for i in eng.state.stack] == ["plain"]
