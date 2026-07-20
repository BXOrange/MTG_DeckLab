"""Tests for GameSession: goldfish play, rewind, restart, multiplayer stub.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md UC3/UC4,
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


def advance_until(session, *, turn=None, step=None, limit=80):
    """Single-step the session until (turn, step) is reached (no auto-skip)."""
    for _ in range(limit):
        st = session.engine.state
        if (turn is None or st.turn_number == turn) and (step is None or st.current_step == step):
            return
        session.apply_action({"type": "advance_step"})
    raise AssertionError(f"never reached turn={turn} step={step}")


class TestStackAndChoices:
    def _advance_to_main1(self, session):
        # Single-stepping (no auto-skip): walk untap/upkeep/draw to main1.
        advance_until(session, step="main1")

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

    def test_cast_spell_forwards_kicked_to_the_engine(self):
        # RULE 702.33: `kicked` must round-trip from the wire action to
        # `GameEngine.cast_spell` the same way `x` already does — the
        # session's `cast_spell` handler used to silently drop the field, so
        # a kicked cast could never be requested through the API at all even
        # though `legal_actions` already offers `has_kicker`/`max_kicker`.
        session = make_session(library=[land()] * 10 + [bear(), land()], hand=7)
        self._advance_to_main1(session)
        state = session.engine.state
        state.active_player.mana_pool.add_many({"G": 1, "C": 1, "R": 1})
        bear_obj = next(o for o in state.active_player.hand if o.card.is_creature)
        bear_obj.parametric_keywords = {"kicker": {"cost": "{R}"}}

        session.apply_action(
            {"type": "cast_spell", "instance_id": bear_obj.instance_id, "kicked": 1}
        )

        assert state.stack[-1].obj.kicker_count == 1
        assert state.active_player.mana_pool.total() == 0

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

    def test_tap_for_mana_with_explicit_tap_choices(self):
        # Birchlore Rangers-shaped cost ("tap two untapped Elves you
        # control") — the player's own choice of which two, round-tripped
        # through the session action as `tap_choices` (RULE 602.1).
        from mtg_analyzer.models.game_object import GameObject, Zone

        def elf(name, oracle):
            return Card(
                id=name, name=name, type_line="Creature — Elf Druid",
                is_creature=True, oracle_text=oracle,
            )

        session = make_session(library=[land()] * 5, hand=0)
        self._advance_to_main1(session)
        state = session.engine.state
        source = GameObject(elf(
            "Birchlore Rangers",
            "Tap two untapped Elves you control: Add one mana of any color.",
        ), owner_id="p1", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(source)
        e1 = GameObject(elf("Llanowar Elves", "{T}: Add {G}."), owner_id="p1", zone=Zone.BATTLEFIELD)
        state.add_to_battlefield(e1)

        # Sanity: legal_actions offers the eligible pool, itself included.
        action = next(
            a for a in session.legal_actions()
            if a["type"] == "tap_for_mana" and a["instance_id"] == source.instance_id
        )
        pool_ids = {o["instance_id"] for o in action["tap_cost"]["options"]}
        assert pool_ids == {source.instance_id, e1.instance_id}

        session.apply_action({
            "type": "tap_for_mana",
            "instance_id": source.instance_id,
            "option_index": 4,  # green
            "tap_choices": [source.instance_id, e1.instance_id],
        })
        assert state.active_player.mana_pool.pool["G"] == 1
        assert source.tapped and e1.tapped

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
        assert session.view()["setup"] == {"complete": True, "mulligan_count": 0, "draw_first": False}


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
        assert view["setup"] == {"complete": False, "mulligan_count": 0, "draw_first": False}
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
        assert view["setup"] == {"complete": False, "mulligan_count": 1, "draw_first": False}
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
        assert view["setup"] == {"complete": True, "mulligan_count": 1, "draw_first": False}
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
        # After setup, normal actions unlock; single-step to main1.
        advance_until(session, step="main1")
        assert session.engine.state.current_step == "main1"

    def test_restart_re_enters_the_setup_phase(self):
        session = self._start()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_step"})
        view = session.restart()
        assert view["setup"] == {"complete": False, "mulligan_count": 0, "draw_first": False}


class TestActions:
    def _advance_to_main1(self, session):
        advance_until(session, step="main1")

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
        advance_until(session, step="main1")  # manually reach main1 of turn 1
        session.apply_action({"type": "auto_turn"})
        # Finishing turn 1 lands on turn 2 — not turn 3 (no double begin_turn).
        assert session.engine.state.turn_number == 2


class TestSingleStep:
    """"advance_step" advances exactly one step — no auto-skip, no auto-wait."""

    def test_one_advance_moves_one_step(self):
        session = make_session()  # fresh game: cursor before the first step
        view = session.apply_action({"type": "advance_step"})
        assert view["state"]["current_step"] == "untap"

    def test_walks_through_every_step_including_empty_ones(self):
        session = make_session(hand=0)  # empty hand: nothing to do anywhere
        seen = []
        for _ in range(6):
            view = session.apply_action({"type": "advance_step"})
            seen.append(view["state"]["current_step"])
        # Main phases and combat steps are visited, not skipped.
        assert seen[:6] == ["untap", "upkeep", "draw", "main1", "begin_combat", "declare_attackers"]


class TestAdvanceToDecision:
    """"advance_to_decision" fast-forwards to the active player's next choice."""

    def test_stops_at_main1(self):
        session = make_session()
        view = session.apply_action({"type": "advance_to_decision"})
        assert view["state"]["current_step"] == "main1"

    def test_does_not_skip_the_main_phase_to_combat(self):
        # Bug 2: a ready creature and nothing castable must NOT cause the main
        # phase to be skipped straight to combat — the main phase is where the
        # player develops their board, so it's always a stopping point.
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = make_session(library=[bear()] * 10, hand=0)  # nothing castable
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        session.apply_action({"type": "advance_to_decision"})
        assert session.engine.state.current_step == "main1"

    def test_second_press_advances_from_main1_to_combat(self):
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = make_session(library=[bear()] * 10, hand=0)
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        session.apply_action({"type": "advance_to_decision"})  # → main1
        session.apply_action({"type": "advance_to_decision"})  # → combat
        assert session.engine.state.current_step == "declare_attackers"

    def test_generates_individual_advance_steps_for_deterministic_undo(self):
        # Bug 1: the fast-forward is a sequence of real advance_step moves,
        # each logged and undoable one at a time — not one opaque jump.
        session = make_session()
        before = len(session.move_log)
        session.apply_action({"type": "advance_to_decision"})
        added = session.move_log[before:]
        assert added == ["advance_step"] * len(added)
        assert len(added) >= 2  # untap/upkeep/draw/main1 were real steps
        stop = session.engine.state.current_step
        session.rewind(1)  # undoes exactly one step, not the whole skip
        assert session.engine.state.current_step != stop

    def test_works_with_the_dummy_opponent_present(self):
        # Bug 1: deterministic step-by-step advance holds with the opponent.
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_to_decision"})
        assert session.engine.state.current_step == "main1"
        assert session.move_log.count("advance_step") >= 2


class TestRewind:
    def test_rewind_undoes_last_move(self):
        session = make_session()
        advance_until(session, step="main1")
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
        # Single-step just into turn 2, then rewind the boundary crossing.
        advance_until(session, turn=2, step="untap")
        assert session.engine.state.turn_number == 2
        session.rewind(1)
        # Restored to the last step of turn 1 (cleanup) — the cursor travels
        # with the snapshot, so the turn counter doesn't jump forward.
        assert session.engine.state.turn_number == 1
        assert session.engine.state.current_step == "cleanup"
        # Continuing crosses the boundary again, not an extra turn.
        session.apply_action({"type": "advance_step"})
        assert session.engine.state.turn_number == 2
        assert session.engine.state.current_step == "untap"

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
        advance_until(session, step="main1")
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
        advance_until(session, step="main2")
        session.restart()
        # From the restored opening state, single-stepping reaches main1 again.
        advance_until(session, step="main1")
        assert session.engine.state.current_step == "main1"
        assert session.engine.state.turn_number == 1


class TestCombat:
    def _to_declare_attackers(self, session):
        engine = session.engine
        while engine.state.current_step != "declare_attackers":
            if engine.advance_step() is None:
                break

    def test_solo_swing_marks_attacking_and_rewind_undoes_it(self):
        session = make_session(hand=0)
        # A ready creature on the battlefield (not summoning-sick).
        from mtg_analyzer.models.game_object import GameObject, Zone

        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        self._to_declare_attackers(session)

        attack = next(
            a for a in session.legal_actions() if a["type"] == "attack"
        )
        assert attack["legal_defenders"] == []  # solo → bare swing
        session.apply_action({"type": "attack", "instance_id": obj.instance_id})
        assert obj.attacking and obj.tapped

        # Rewind restores the pre-attack state — combat lives on the state,
        # so the freshly-restored engine sees the creature un-declared.
        session.rewind(1)
        restored = session.engine.state.find_object(obj.instance_id)
        assert not restored.attacking and not restored.tapped

    def test_attack_serializes_combat_state_to_the_view(self):
        session = make_session(hand=0)
        from mtg_analyzer.models.game_object import GameObject, Zone

        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        session.engine.state.add_to_battlefield(obj)
        self._to_declare_attackers(session)
        view = session.apply_action(
            {"type": "attack", "instance_id": obj.instance_id}
        )
        card = next(
            c for c in view["state"]["battlefield"] if c["instance_id"] == obj.instance_id
        )
        assert card["attacking"] is True
        assert card["type_line"] == "Creature — Bear"
        assert card["is_creature"] is True


class TestGoldfishDummy:
    def _keep(self, session):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})

    def test_real_goldfish_has_a_passive_dummy_opponent(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40, starting_life=20)
        players = session.view()["state"]["players"]
        assert len(players) == 2
        dummy = next(p for p in players if p["is_dummy"])
        assert dummy["name"] == "Goldfisch"
        assert dummy["life"] == 20
        assert dummy["hand_count"] == 7  # a hand to discard from, hidden in UI

    def test_dummy_never_becomes_active_player(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        self._keep(session)
        start = session.engine.state.active_player.id
        assert start == "p1"
        # Run several whole turns; the turn always comes back to the human.
        for _ in range(40):
            if session.engine.advance_step() is None:
                break
        assert session.engine.state.active_player.id == "p1"
        assert session.engine.state.turn_number >= 2  # turns did advance

    def test_view_carries_analysis_digest(self):
        session = GameSessionManager().create_goldfish(library=[land()] * 40)
        self._keep(session)
        analysis = session.view()["analysis"]
        assert set(analysis["players"]) == {"p1", "goldfish"}
        p1 = analysis["players"]["p1"]
        for key in ("cmc_curve", "mana_per_turn", "cards_played", "avg_cmc"):
            assert key in p1

    def test_attacking_the_goldfish_deals_and_records_damage(self):
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = GameSessionManager().create_goldfish(library=[land()] * 40, starting_life=20)
        self._keep(session)
        st = session.engine.state
        obj = GameObject(bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        st.add_to_battlefield(obj)
        while st.current_step != "declare_attackers":
            if session.engine.advance_step() is None:
                break
        session.apply_action({"type": "declare_attackers", "instance_ids": [obj.instance_id]})
        while st.current_step != "combat_damage":
            if session.engine.advance_step() is None:
                break
        view = session.view()
        dummy = next(p for p in view["state"]["players"] if p["is_dummy"])
        assert dummy["life"] == 18  # 2/2 bear
        assert view["analysis"]["players"]["p1"]["damage_dealt"] == 2


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
