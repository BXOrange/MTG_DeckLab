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


def shock():
    return Card(
        id="Shock",
        name="Shock",
        type_line="Instant",
        mana_cost_string="{R}",
        converted_mana_cost=1,
        is_instant=True,
    )


def make_session(library=None, commanders=None, hand=7):
    library = library if library is not None else [land()] * 30
    engine = build_goldfish_engine(library, commanders=commanders, starting_hand=hand)
    return GameSession(engine)


class TestStackAndChoices:
    def _advance_to_main1(self, session):
        # Untap/upkeep/draw offer no choice, so one "advance_step" call
        # auto-skips through all of them and stops at main1 (the first
        # step with something to do — a land in hand to play).
        session.apply_action({"type": "advance_step"})

    def test_cast_leaves_spell_on_stack_and_pass_priority_resolves_it(self):
        # A land + a bear on top of the library so both reach the hand.
        session = make_session(library=[land()] * 10 + [bear(), land()], hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        # Play a land and tap it, then a second land next turn is overkill —
        # give mana directly for a focused test.
        state.active_player.mana_pool.add_many({"G": 1, "C": 1})
        bear_obj = next(o for o in state.active_player.hand if o.card.is_creature)
        view = session.apply_action(
            {"type": "cast_spell", "instance_id": bear_obj.instance_id}
        )
        # The spell is on the stack, not yet resolved.
        assert len(view["state"]["stack"]) == 1
        assert bear_obj.instance_id not in {o["instance_id"] for o in view["state"]["battlefield"]}
        # Passing priority resolves it onto the battlefield.
        view = session.apply_action({"type": "pass_priority"})
        assert len(view["state"]["stack"]) == 0
        assert bear_obj.instance_id in {o["instance_id"] for o in view["state"]["battlefield"]}

    def test_tap_for_mana_with_option_index(self):
        session = make_session(library=[land()] * 10, hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        land_obj = next(o for o in state.active_player.hand if o.card.is_land)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})
        session.apply_action(
            {"type": "tap_for_mana", "instance_id": land_obj.instance_id, "option_index": 0}
        )
        assert state.active_player.mana_pool.pool["G"] == 1

    def test_pending_search_gates_actions_and_choose_completes_it(self):
        from mtg_analyzer.models.game_state import StackItem
        from mtg_analyzer.game.effects import SearchLibraryEffect

        session = make_session(library=[bear(), land(), bear()], hand=0)
        state = session.engine.state
        player = state.active_player
        ability = SearchLibraryEffect(type_restriction="Creature", player=player)
        state.stack.append(StackItem(kind="ability", controller_id=player.id, effects=[ability]))

        view = session.apply_action({"type": "pass_priority"})
        # A choice is pending; legal_actions offers only choose/decline.
        assert view["pending_choice"] is not None
        types = {a["type"] for a in view["legal_actions"]}
        assert types <= {"choose", "decline"}

        # A non-choice action is rejected while pending.
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_step"})

        target = view["pending_choice"]["eligible"][0]["instance_id"]
        view = session.apply_action({"type": "choose", "instance_id": target})
        assert view["pending_choice"] is None
        assert any(o["instance_id"] == target for o in view["state"]["players"][0]["hand"])


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

    def test_direct_session_construction_skips_the_setup_phase_by_default(self):
        # `make_session()` builds a `GameSession` directly (as most tests in
        # this file do) to exercise the turn loop without a mulligan step in
        # the way; only `GameSessionManager.create_goldfish` (below) opts a
        # real goldfish game into `require_setup`.
        session = make_session()
        assert session.view()["setup"] == {"complete": True, "mulligan_count": 0}


class TestMulligan:
    """UC3: a goldfish game from the manager gates on mulligan/keep_hand first."""

    def _start(self, library=None, commanders=None, hand=7):
        manager = GameSessionManager()
        library = library if library is not None else [land()] * 30
        return manager.create_goldfish(
            library=library, commanders=commanders, starting_hand=hand
        )

    def test_starts_incomplete_with_only_mulligan_actions(self):
        session = self._start()
        view = session.view()
        assert view["setup"] == {"complete": False, "mulligan_count": 0}
        assert {a["type"] for a in view["legal_actions"]} == {"mulligan", "keep_hand"}

    def test_non_setup_actions_are_rejected_until_kept(self):
        session = self._start()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_step"})

    def test_mulligan_reshuffles_hand_and_redraws_seven(self):
        session = self._start()
        player = session.engine.state.active_player
        first_hand = {o.instance_id for o in player.hand}
        view = session.apply_action({"type": "mulligan"})
        assert view["setup"] == {"complete": False, "mulligan_count": 1}
        assert len(player.hand) == 7
        # A fresh 7 from a reshuffled 30-card library of identical basics
        # can't be asserted against by name, but the instances differ.
        assert {o.instance_id for o in player.hand} != first_hand

    def test_keep_hand_requires_bottoming_one_card_per_mulligan(self):
        session = self._start()
        session.apply_action({"type": "mulligan"})
        with pytest.raises(GameActionError):
            session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

        player = session.engine.state.active_player
        bottom_id = player.hand[0].instance_id
        view = session.apply_action(
            {"type": "keep_hand", "bottom_instance_ids": [bottom_id]}
        )
        assert view["setup"] == {"complete": True, "mulligan_count": 1}
        assert len(player.hand) == 6
        assert player.library[0].instance_id == bottom_id

    def test_keeping_the_opening_hand_needs_no_bottoming(self):
        session = self._start()
        view = session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        assert view["setup"]["complete"] is True
        assert len(session.engine.state.active_player.hand) == 7

    def test_setup_complete_unlocks_normal_actions(self):
        session = self._start()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        # Untap/upkeep/draw have nothing to decide, so the auto-skip
        # carries straight through to main1 (a land is in hand to play).
        view = session.apply_action({"type": "advance_step"})
        assert view["state"]["current_step"] == "main1"

    def test_restart_re_enters_the_setup_phase(self):
        session = self._start()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_step"})
        view = session.restart()
        assert view["setup"] == {"complete": False, "mulligan_count": 0}


class TestActions:
    def _advance_to_main1(self, session):
        # untap/upkeep/draw are auto-skipped (nothing to decide there).
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
        session.apply_action({"type": "advance_step"})  # manually reach main1 of turn 1
        session.apply_action({"type": "auto_turn"})
        # Finishing turn 1 lands on turn 2 — not turn 3 (no double begin_turn).
        assert session.engine.state.turn_number == 2


class TestAutoAdvanceStep:
    """Default UX (docs/02 R4.1): "advance_step" auto-skips steps with
    nothing to decide, stopping at the first one that offers a real choice.
    """

    def test_skips_untap_upkeep_and_draw_when_nothing_to_do(self):
        session = make_session()  # all-basics deck: a land to play in main1
        view = session.apply_action({"type": "advance_step"})
        assert view["state"]["current_phase"] == "precombat_main"
        assert view["state"]["current_step"] == "main1"

    def test_castable_spell_counts_as_interaction(self):
        # An affordable instant is a real choice wherever it comes up —
        # not just in a main phase — so a step where one is castable must
        # not be auto-skipped.
        session = make_session(library=[land()] * 5 + [shock()], hand=1)
        session.engine.state.active_player.mana_pool.add_many({"R": 1})
        assert session._step_has_interaction() is True

    def test_bare_mana_ability_does_not_count_as_interaction(self):
        # Tapping a land for mana is legal in every step but empties again
        # at that step's end, so having one untapped, alone, isn't a
        # reason to stop the auto-skip.
        from mtg_analyzer.models.game_object import GameObject

        session = make_session(hand=0)
        session.engine.state.add_to_battlefield(GameObject(land(), owner_id="p1"))
        assert session._step_has_interaction() is False

    def test_non_empty_stack_counts_as_interaction(self):
        from mtg_analyzer.models.game_state import StackItem

        session = make_session(hand=0)
        session.engine.state.stack.append(
            StackItem(kind="ability", controller_id="p1", description="test")
        )
        assert session._step_has_interaction() is True

    def test_pending_choice_counts_as_interaction(self):
        session = make_session(hand=0)
        session.engine.state.pending_choice = {"kind": "search", "eligible": []}
        assert session._step_has_interaction() is True


class TestRewind:
    def test_rewind_undoes_last_move(self):
        session = make_session()
        session.apply_action({"type": "advance_step"})  # auto-skips to main1
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
        # An all-land deck never runs out of a legal `play_land`, so both
        # main phases stop the auto-skip: main1(t1) -> main2(t1) -> main1(t2).
        for _ in range(3):
            session.apply_action({"type": "advance_step"})
        assert session.engine.state.turn_number == 2
        session.rewind(1)
        # Restored to turn 1 (main2) without jumping the turn counter forward.
        assert session.engine.state.turn_number == 1
        assert session.engine.state.current_step == "main2"
        # Continuing advances to the next stopping point, not an extra turn.
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.turn_number == 2

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
        session.apply_action({"type": "advance_step"})  # auto-skips to main1
        land_obj = next(o for o in session.engine.state.active_player.hand if o.card.is_land)
        session.apply_action({"type": "play_land", "instance_id": land_obj.instance_id})

        session.restart()
        state = session.engine.state
        assert state.turn_number == 1
        assert len(state.active_player.hand) == 7
        assert len(state.battlefield) == 0
        assert not session.can_rewind
        assert session.move_log == []

    def test_restart_then_advance_reaches_main1(self):
        session = make_session()
        for _ in range(3):
            session.apply_action({"type": "advance_step"})
        session.restart()
        # Untap/upkeep/draw are auto-skipped again from the restored
        # opening state, landing straight on main1.
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.current_step == "main1"
        assert session.engine.state.turn_number == 1


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
