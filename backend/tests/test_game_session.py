"""Tests for GameSession: goldfish play, rewind, restart, multiplayer stub.

Reference: docs/02_MVP_USECASES_REVISED.md UC3/UC4,
mtg_analyzer/services/game_session.py.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.services.game_session import (
    GameActionError,
    GameSession,
    GameSessionManager,
    MultiplayerNotImplementedError,
    build_goldfish_engine,
)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def bear():
    return Card(
        id="Grizzly Bears",
        name="Grizzly Bears",
        type_line="Creature — Bear",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=2,
        toughness=2,
        color_identity={"G"},
    )


def make_session(library=None, commanders=None, hand=7):
    library = library if library is not None else [land()] * 30
    engine = build_goldfish_engine(library, commanders=commanders, starting_hand=hand)
    return GameSession(engine)


class TestSetup:
    def test_opening_hand_is_dealt_and_commander_in_command_zone(self):
        session = make_session(commanders=[bear()])
        player = session.engine.state.active_player
        assert len(player.hand) == 7
        assert len(player.command) == 1
        assert session.engine.state.turn_number == 1

    def test_view_has_state_and_legal_actions(self):
        view = make_session().view()
        assert view["mode"] == "goldfish"
        assert "state" in view and "legal_actions" in view
        assert view["can_rewind"] is False


class TestActions:
    def _advance_to_main1(self, session):
        for _ in range(4):  # untap, upkeep, draw, main1
            session.apply_action({"type": "advance_step"})

    def test_play_land_then_action_is_recorded(self):
        session = make_session()
        self._advance_to_main1(session)
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        session.apply_action(
            {"type": "play_land", "instance_id": land_obj.instance_id, "name": land_obj.name}
        )
        assert land_obj.instance_id in {o.instance_id for o in state.battlefield}
        assert session.can_rewind
        assert session.move_log[-1].startswith("play_land")

    def test_illegal_action_raises_and_leaves_state_untouched(self):
        session = make_session()
        # Trying to play a land during untap is illegal.
        land_obj = next(o for o in session.engine.state.active_player.hand if o.card.is_land)
        before_hand = len(session.engine.state.active_player.hand)
        with pytest.raises(GameActionError):
            session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        assert len(session.engine.state.active_player.hand) == before_hand
        assert not session.can_rewind  # failed action left no undo entry

    def test_unknown_instance_id_raises(self):
        session = make_session()
        self._advance_to_main1(session)
        with pytest.raises(GameActionError):
            session.apply_action({"type": "play_land", "instance_id": 999999})

    def test_unknown_action_type_raises(self):
        session = make_session()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "teleport"})

    def test_auto_turn_plays_out_one_turn_and_is_undoable(self):
        session = make_session()
        session.apply_action({"type": "auto_turn"})
        # Auto-turn drives the cursor (not a fresh begin_turn), ending at
        # the next turn without desyncing.
        assert session.engine.state.turn_number == 2
        # The whole auto-turn is a single undo step back to the opening.
        session.rewind(1)
        assert session.engine.state.turn_number == 1

    def test_auto_turn_resumes_from_a_mid_turn_manual_position(self):
        session = make_session()
        for _ in range(4):  # manually reach main1 of turn 1
            session.apply_action({"type": "advance_step"})
        session.apply_action({"type": "auto_turn"})
        # Finishing turn 1 lands on turn 2 — not turn 3 (no double begin_turn).
        assert session.engine.state.turn_number == 2


class TestRewind:
    def test_rewind_undoes_last_move(self):
        session = make_session()
        for _ in range(4):
            session.apply_action({"type": "advance_step"})
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        hand_before = len(state.active_player.hand)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        session.rewind(1)
        # Back to before the land drop.
        assert len(session.engine.state.active_player.hand) == hand_before
        assert len(session.engine.state.battlefield) == 0

    def test_rewind_across_turn_boundary_resumes_mid_turn(self):
        session = make_session()
        for _ in range(14):  # cross into turn 2
            session.apply_action({"type": "advance_step"})
        assert session.engine.state.turn_number == 2
        session.rewind(3)
        # Restored to turn 1 without jumping the turn counter forward.
        assert session.engine.state.turn_number == 1
        # Continuing advances one step at a time, not a whole turn.
        step_before = session.engine.state.current_step
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.turn_number == 1

    def test_rewind_more_than_history_restarts(self):
        session = make_session()
        session.apply_action({"type": "advance_step"})
        session.rewind(10)
        assert not session.can_rewind
        assert session.engine.state.turn_number == 1

    def test_rewind_requires_positive_steps(self):
        session = make_session()
        with pytest.raises(GameActionError):
            session.rewind(0)


class TestRestart:
    def test_restart_returns_to_opening_state(self):
        session = make_session()
        for _ in range(4):
            session.apply_action({"type": "advance_step"})
        land_obj = next(o for o in session.engine.state.active_player.hand if o.card.is_land)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})

        session.restart()
        state = session.engine.state
        assert state.turn_number == 1
        assert len(state.active_player.hand) == 7
        assert len(state.battlefield) == 0
        assert not session.can_rewind
        assert session.move_log == []

    def test_restart_then_advance_starts_from_untap(self):
        session = make_session()
        for _ in range(6):
            session.apply_action({"type": "advance_step"})
        session.restart()
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.current_step == "untap"


class TestManager:
    def test_create_and_get_goldfish(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert manager.get(session.id) is session

    def test_get_unknown_raises_keyerror(self):
        manager = GameSessionManager()
        with pytest.raises(KeyError):
            manager.get("nope")

    def test_remove(self):
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert manager.remove(session.id) is True
        assert manager.remove(session.id) is False

    def test_multiplayer_is_a_stub(self):
        manager = GameSessionManager()
        with pytest.raises(MultiplayerNotImplementedError):
            manager.create_multiplayer()
