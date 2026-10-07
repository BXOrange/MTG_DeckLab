"""MEC-113 / RULE 610.3: immediate returns, source/exile incarnations and simultaneity."""
import pytest

from mtg_analyzer.game.effects.exile_control import ExileEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import game, card, filler, enter, answer, pick_label


def _prison(engine, name="Portable Hole"):
    victim = filler(engine, "Victim", player="p2", mv=1, power=2, toughness=2)
    source = card(engine, name)
    enter(engine, source)
    answer(engine, pick_label("Victim"))
    assert victim.zone == Zone.EXILE
    return source, victim


@pytest.mark.parametrize("departure", ["put_into_graveyard", "exile", "return_to_hand"])
def test_return_is_immediate_and_has_no_return_trigger(departure):
    engine = game()
    source, victim = _prison(engine)
    getattr(engine.rules, departure)(source)
    assert victim in engine.state.battlefield
    assert victim.controller_id == victim.owner_id == "p2"
    assert not engine.state.stack
    assert not engine.rules.pending_triggers
    assert not engine.state.until_source_leaves_exiles


@pytest.mark.parametrize("blink", [False, True])
def test_source_departure_before_trigger_resolution_prevents_exile(blink):
    engine = game()
    victim = filler(engine, "Victim", player="p2", mv=1, power=2, toughness=2)
    source = card(engine, "Portable Hole")
    enter(engine, source)  # pauses at the real triggered-target announcement
    assert engine.state.pending_choice
    engine.rules.return_to_hand(source)
    if blink:
        engine.rules.return_from_graveyard(source, "battlefield")
    choice = engine.state.pending_choice
    engine.resolve_pending_choice(pick_label("Victim")(choice))
    assert victim.zone == Zone.BATTLEFIELD
    assert not engine.state.until_source_leaves_exiles


def test_each_activation_has_an_independent_link_and_exile_incarnation():
    engine = game()
    source, first = _prison(engine)
    second = filler(engine, "Second", player="p2", power=2, toughness=2)
    effect = ExileEffect(source=source, until_source_leaves=True)
    effect.apply(engine.rules.context, [second])
    # Leaving and reentering exile breaks the original link.
    engine.rules.return_to_hand(first)
    engine.rules.exile(first)
    engine.rules.put_into_graveyard(source)
    assert first.zone == Zone.EXILE
    assert second.zone == Zone.BATTLEFIELD


def test_simultaneous_source_departures_return_all_cards_before_entry_triggers():
    engine = game()
    source1, first = _prison(engine)
    source2, second = _prison(engine)
    arrivals = []
    engine.state.subscribe(lambda e: arrivals.append(set(o.instance_id for o in engine.state.battlefield))
                           if e.type == EventType.ENTERS_BATTLEFIELD else None)
    with engine.state.simultaneous():
        engine.rules.put_into_graveyard(source1)
        engine.rules.put_into_graveyard(source2)
        assert first.zone == second.zone == Zone.EXILE
    assert len(arrivals) == 2
    assert all({first.instance_id, second.instance_id} <= snapshot for snapshot in arrivals)


def test_links_survive_a_state_snapshot_and_rebuilt_engine():
    engine = game()
    source, victim = _prison(engine)
    restored = GameEngine(engine.state.clone())
    source = restored.state.find_object(source.instance_id)
    victim = restored.state.find_object(victim.instance_id)
    restored.rules.exile(source)
    assert victim.zone == Zone.BATTLEFIELD


def test_activated_exile_does_not_follow_a_blinked_source():
    engine = game()
    source = filler(engine, "Prison", type_line="Artifact")
    victim = filler(engine, "Victim", player="p2", power=2, toughness=2)
    engine.state.stack.append(StackItem("ability", "p1", source=source, targets=[victim],
                                       effects=[ExileEffect(source=source, until_source_leaves=True)]))
    engine.rules.return_to_hand(source)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.rules.resolve_top_of_stack()
    assert victim.zone == Zone.BATTLEFIELD


def test_legacy_two_ability_exile_retains_the_return_trigger():
    engine = game()
    victim = filler(engine, "Victim", type_line="Artifact", player="p2", mv=1)
    source = card(engine, "Leonin Relic-Warder")
    enter(engine, source)
    answer(engine, pick_label("Victim"))
    assert victim.zone == Zone.EXILE
    engine.rules.put_into_graveyard(source)
    assert victim.zone == Zone.EXILE
    engine.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD
