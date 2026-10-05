"""VIS-12: one-shot yields ("Pass this turn", "Skip to end step") and standing
per-step stops, played out server-side in a shared game.

Reference: mtg_analyzer/services/game_session.py (`_auto_pass_followups`,
`_yield_wants_pass`), RULE 117.3-4. A yield may only ever skip *this seat's*
windows, and never one with another player's spell or ability to respond to.
"""

import pytest

from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.services.game_session import GameActionError

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.game_session import GameSessionManager


def make_game():
    """A two-seat shared game, both seats holding the same 30-land pile."""
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    return GameSessionManager().create_multiplayer(
        [
            {"player_id": "ann", "name": "Ann", "library": [land] * 30},
            {"player_id": "bob", "name": "Bob", "library": [land] * 30},
        ],
        mulligan_style="london",
    )


def keep_all(session):
    for pid in ("ann", "bob"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)


def playing():
    session = make_game()
    keep_all(session)
    return session


def act(session, kind, actor, **extra):
    return session.apply_action({"type": kind, **extra}, actor_id=actor)


def bob_passes_until(session, step, turn=1, limit=60):
    """Drive only Bob (the human who is *not* yielding) until ``step``."""
    for _ in range(limit):
        state = session.engine.state
        if state.current_step == step and state.internal_turn.number == turn:
            return
        holder = state.priority_player
        assert holder is not None and holder.id == "bob", (
            f"expected Bob to hold priority at {state.current_step!r}, got {holder and holder.id}"
        )
        act(session, "pass_priority", "bob")
    raise AssertionError(f"never reached {step!r}")


def put_on_stack(state, controller):
    """``controller`` puts an ability on the stack — which, like any action,
    reopens the round (RULE 117.3c: earlier passes no longer count)."""
    state.stack.append(StackItem("ability", controller, effects=[]))
    state.priority_passed.clear()


class TestPassThisTurn:
    """Bob yields on Ann's turn: "Pass this turn" is for opponents' turns."""

    def test_the_yielding_seat_is_passed_for_until_that_turn_ends(self):
        session = playing()
        act(session, "set_yield", "bob", mode="turn")
        state = session.engine.state
        for _ in range(40):
            if state.internal_turn.number != 1:
                break
            # Every window of Ann's turn is hers alone: Bob is passed for.
            assert state.priority_player.id == "ann"
            act(session, "pass_priority", "ann")
        # Turn 2 is Bob's own: the yield (for Ann's turn) is gone and he, the
        # active player, holds priority in his own upkeep.
        assert state.internal_turn.number == 2
        assert state.active_player.id == "bob"
        assert state.priority_player.id == "bob"
        assert session.view(perspective="bob")["priority"]["yields"] == {}

    def test_another_players_spell_on_the_stack_interrupts(self):
        session = playing()
        act(session, "set_yield", "bob", mode="turn")
        state = session.engine.state
        put_on_stack(state, "ann")
        act(session, "pass_priority", "ann")
        # Bob is *not* passed for: there is something to respond to.
        assert state.priority_player.id == "bob"
        assert len(state.stack) == 1
        # He lets it resolve; the yield is still armed and carries on.
        act(session, "pass_priority", "bob")
        assert state.stack == []
        assert state.priority_player.id == "ann"
        assert session.view(perspective="bob")["priority"]["yields"] == {"bob": "turn"}

    def test_clear_disarms_from_an_interruption_window(self):
        session = playing()
        act(session, "set_yield", "bob", mode="turn")
        state = session.engine.state
        put_on_stack(state, "ann")
        act(session, "pass_priority", "ann")
        assert state.priority_player.id == "bob"
        act(session, "set_yield", "bob", mode="clear")
        assert session.view(perspective="bob")["priority"]["yields"] == {}
        # No longer passed for: Ann passes on the empty stack and Bob is asked.
        act(session, "pass_priority", "bob")
        act(session, "pass_priority", "ann")
        assert state.priority_player.id == "bob"

    def test_it_can_be_armed_without_holding_priority(self):
        session = playing()
        assert session.engine.state.priority_player.id == "ann"
        act(session, "set_yield", "bob", mode="turn")
        assert session.view(perspective="bob")["priority"]["yields"] == {"bob": "turn"}

    def test_it_is_refused_on_your_own_turn(self):
        session = playing()
        with pytest.raises(GameActionError, match="opponent's turn"):
            act(session, "set_yield", "ann", mode="turn")

    def test_unknown_mode_is_refused(self):
        session = playing()
        with pytest.raises(GameActionError, match="unknown yield mode"):
            act(session, "set_yield", "ann", mode="forever")


class TestSkipToEndStep:
    def test_stops_at_the_end_step_and_disarms(self):
        session = playing()
        act(session, "set_yield", "ann", mode="end_step")
        bob_passes_until(session, "end")
        state = session.engine.state
        # Arrived: the yield disarmed itself and Ann holds priority here.
        assert state.current_step == "end"
        assert state.priority_player.id == "ann"
        assert session.view(perspective="ann")["priority"]["yields"] == {}

    def test_an_opponents_spell_interrupts_it_too(self):
        session = playing()
        act(session, "set_yield", "ann", mode="end_step")
        state = session.engine.state
        put_on_stack(state, "bob")
        act(session, "pass_priority", "bob")
        assert state.priority_player.id == "ann"
        assert session.view(perspective="ann")["priority"]["yields"] == {"ann": "end_step"}

    def test_it_is_refused_on_an_opponents_turn(self):
        session = playing()
        with pytest.raises(GameActionError, match="your own turn"):
            act(session, "set_yield", "bob", mode="end_step")


class TestStops:
    def test_a_seat_without_stops_is_asked_everywhere(self):
        session = playing()
        act(session, "pass_priority", "ann")
        assert session.engine.state.priority_player.id == "bob"
        assert session.view(perspective="bob")["priority"]["stops"] == {}

    def test_no_stop_on_the_opponents_turn_passes_for_the_seat(self):
        session = playing()
        act(session, "set_stops", "bob", own=["upkeep", "main1", "main2"], opponent=["main1"])
        state = session.engine.state
        # Ann passes upkeep; Bob has no upkeep stop on her turn → passed for,
        # so the step ends and Ann holds priority in the draw step.
        act(session, "pass_priority", "ann")
        assert state.current_step == "draw"
        assert state.priority_player.id == "ann"
        # …but main1 is a stop: Bob is asked there.
        act(session, "pass_priority", "ann")
        assert state.current_step == "main1"
        act(session, "pass_priority", "ann")
        assert state.priority_player.id == "bob"

    def test_a_stop_never_swallows_a_spell_to_respond_to(self):
        session = playing()
        act(session, "set_stops", "bob", own=[], opponent=[])
        state = session.engine.state
        state.stack.append(StackItem("ability", "ann", effects=[]))
        act(session, "pass_priority", "ann")
        assert state.priority_player.id == "bob"

    def test_the_main_phases_cannot_be_unstopped_on_your_own_turn(self):
        session = playing()
        act(session, "set_stops", "ann", own=[], opponent=[])
        assert session.view(perspective="ann")["priority"]["stops"]["ann"]["own"] == [
            "main1", "main2",
        ]

    def test_unknown_step_is_refused(self):
        session = playing()
        with pytest.raises(GameActionError, match="unknown step"):
            act(session, "set_stops", "ann", own=["cleanup"], opponent=[])


class TestNextStep:
    """The "Pass" button names where passing leads (`priority.next_step`)."""

    def test_it_follows_the_turn_and_skips_steps_nobody_gets_priority_in(self):
        session = playing()
        seen = []
        state = session.engine.state
        while state.internal_turn.number == 1:
            seen.append((state.current_step, session.view(perspective="ann")["priority"]["next_step"]))
            act(session, "pass_priority", state.priority_player.id)
        assert seen[0] == ("upkeep", "draw")
        assert dict(seen)["main1"] == "begin_combat"
        assert dict(seen)["end_combat"] == "main2"
        # Past the end step only cleanup remains (no priority): next is a new turn.
        assert dict(seen)["end"] == "next_turn"
