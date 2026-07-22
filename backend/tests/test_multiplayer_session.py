"""Tests for the multiplayer half of GameSession (UC4).

Reference: mtg_analyzer/services/game_session.py, docs/requirements/
02_MVP_USECASES_REVISED.md UC4.

Covers what a *shared* session adds over the solo one: every seat
mulligans for itself, actions are attributed to an actor (and refused when
that actor may not take them), views are redacted per seat so hidden zones
(RULE 400.2) never leave the server, blockers can be declared by the
defending player, and conceding (RULE 104.3a) ends the game.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.services.game_session import (
    GameActionError,
    GameSessionManager,
    MULLIGAN_STYLES,
)


def land(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def bear(name="Grizzly Bears"):
    return Card(
        id=name,
        name=name,
        type_line="Creature — Bear",
        mana_cost_string="{1}{G}",
        converted_mana_cost=2,
        is_creature=True,
        power=2,
        toughness=2,
        color_identity={"G"},
    )


def make_game(mulligan_style="london", library=None):
    """A two-seat game, both seats holding the same 30-card pile."""
    manager = GameSessionManager()
    deck = library if library is not None else [land()] * 30
    return manager.create_multiplayer(
        [
            {"player_id": "ann", "name": "Ann", "library": list(deck)},
            {"player_id": "bob", "name": "Bob", "library": list(deck)},
        ],
        mulligan_style=mulligan_style,
    )


def keep_all(session):
    for pid in ("ann", "bob"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)


def advance_until(session, *, step=None, turn=None, limit=200):
    """Play forward by *passing priority*, the only way a step ends now.

    Each pass either hands priority to the next player (RULE 117.3-4) or,
    when it completes the round on an empty stack, ends the step — so
    driving whoever currently holds priority walks the game forward.
    """
    for _ in range(limit):
        state = session.engine.state
        if (step is None or state.current_step == step) and (
            turn is None or state.turn_number == turn
        ):
            return
        holder = state.priority_player
        assert holder is not None, f"nobody holds priority at {state.current_step!r}"
        session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
    raise AssertionError(f"never reached step={step!r} turn={turn!r}")


class TestSetup:
    def test_both_seats_get_a_hand_and_the_game_waits_for_both(self):
        session = make_game()
        assert [p.id for p in session.engine.state.players] == ["ann", "bob"]
        assert all(len(p.hand) == 7 for p in session.engine.state.players)
        assert session.view(perspective="ann")["setup"]["waiting_for"] == ["ann", "bob"]

    def test_each_seat_mulligans_independently(self):
        session = make_game()
        session.apply_action({"type": "mulligan"}, actor_id="ann")
        assert session.mulligan_count_for("ann") == 1
        assert session.mulligan_count_for("bob") == 0
        # Ann must now bottom one card; Bob still bottoms none.
        assert session.view(perspective="ann")["setup"]["mulligan_count"] == 1
        assert session.view(perspective="bob")["setup"]["mulligan_count"] == 0

    def test_play_starts_only_once_every_seat_has_kept(self):
        session = make_game()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        assert session.view(perspective="ann")["setup"]["complete"] is False
        assert session.view(perspective="ann")["setup"]["waiting_for"] == ["bob"]
        # A seat that has kept has nothing left to do and can't act yet.
        assert session.legal_actions("ann") == []
        with pytest.raises(GameActionError):
            session.apply_action({"type": "advance_step"}, actor_id="ann")

        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="bob")
        assert session.view(perspective="ann")["setup"]["complete"] is True

    def test_a_kept_seat_cannot_mulligan_again(self):
        session = make_game()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        with pytest.raises(GameActionError):
            session.apply_action({"type": "mulligan"}, actor_id="ann")

    def test_mulligan_style_none_offers_no_mulligan(self):
        session = make_game(mulligan_style="none")
        assert [a["type"] for a in session.legal_actions("ann")] == ["keep_hand"]
        with pytest.raises(GameActionError):
            session.apply_action({"type": "mulligan"}, actor_id="ann")

    def test_unknown_mulligan_style_falls_back_to_london(self):
        session = make_game(mulligan_style="calgary")
        assert session.mulligan_style == "london"
        assert "london" in MULLIGAN_STYLES

    def test_fewer_than_two_seats_is_refused(self):
        from mtg_analyzer.services.game_session import MultiplayerNotImplementedError

        with pytest.raises(MultiplayerNotImplementedError):
            GameSessionManager().create_multiplayer(
                [{"player_id": "ann", "name": "Ann", "library": [land()]}]
            )


class TestRedaction:
    """RULE 400.2: a hand and a library are hidden zones — server-side."""

    def test_opponents_hand_never_leaves_the_server(self):
        session = make_game()
        view = session.view(perspective="ann")
        players = {p["id"]: p for p in view["state"]["players"]}
        assert len(players["ann"]["hand"]) == 7
        assert players["bob"]["hand"] == []
        # …but the *count* is still there, so the board can draw card backs.
        assert players["bob"]["hand_count"] == 7

    def test_libraries_are_hidden_from_everyone_including_their_owner(self):
        session = make_game()
        players = {p["id"]: p for p in session.view(perspective="ann")["state"]["players"]}
        assert players["ann"]["library"] == []
        assert players["bob"]["library"] == []
        assert players["ann"]["library_count"] == 23  # 30 minus the opening hand

    def test_observer_sees_nobody_hand(self):
        session = make_game()
        view = session.observer_view()
        assert all(p["hand"] == [] for p in view["state"]["players"])
        assert all(p["hand_count"] == 7 for p in view["state"]["players"])
        assert view["legal_actions"] == []
        assert view["observer"] is True

    def test_unredacted_view_is_unchanged_for_solo_modes(self):
        session = make_game()
        view = session.view()
        assert all(len(p["hand"]) == 7 for p in view["state"]["players"])
        assert view["perspective"] is None


class TestActorScopedActions:
    def test_nobody_can_force_a_step_to_end(self):
        # RULE 117.4: a step ends when everyone passes, not because someone
        # decided it should — so `advance_step` is refused for both seats.
        session = make_game()
        keep_all(session)
        assert session.engine.state.active_player.id == "ann"
        for pid in ("ann", "bob"):
            with pytest.raises(GameActionError):
                session.apply_action({"type": "advance_step"}, actor_id=pid)

    def test_legal_actions_are_computed_for_the_asking_seat(self):
        session = make_game(library=[land()] * 30)
        keep_all(session)
        advance_until(session, step="main1")
        # Ann is active and holds lands, so she may play one; Bob may not
        # (RULE 305.1 — a land is a sorcery-speed play on your own turn).
        assert any(a["type"] == "play_land" for a in session.legal_actions("ann"))
        assert not any(a["type"] == "play_land" for a in session.legal_actions("bob"))

    def test_an_unknown_actor_is_rejected(self):
        session = make_game()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "keep_hand"}, actor_id="nobody")


class TestBlocking:
    def _combat_session(self):
        session = make_game(library=[bear()] + [land()] * 29)
        keep_all(session)
        return session

    def test_defender_is_offered_blocks_and_can_declare_them(self):
        session = self._combat_session()
        state = session.engine.state
        # Put one creature on each side directly — the point here is the
        # blocking offer/declaration, not how they got onto the battlefield.
        from mtg_analyzer.models.game_object import GameObject, Zone

        attacker = GameObject(bear("Attacker"), owner_id="ann", zone=Zone.BATTLEFIELD)
        attacker.controller_id = "ann"
        attacker.summoning_sick = False
        blocker = GameObject(bear("Blocker"), owner_id="bob", zone=Zone.BATTLEFIELD)
        blocker.controller_id = "bob"
        blocker.summoning_sick = False
        state.add_to_battlefield(attacker)
        state.add_to_battlefield(blocker)

        advance_until(session, step="declare_attackers")
        session.apply_action(
            {"type": "attack", "instance_ids": [attacker.instance_id]}, actor_id="ann"
        )
        advance_until(session, step="declare_blockers")

        offers = [a for a in session.legal_actions("bob") if a["type"] == "declare_blockers"]
        assert [o["instance_id"] for o in offers] == [blocker.instance_id]
        assert offers[0]["legal_attackers"][0]["instance_id"] == attacker.instance_id
        # The attacking player is never offered blocks.
        assert not any(a["type"] == "declare_blockers" for a in session.legal_actions("ann"))

        session.apply_action(
            {
                "type": "declare_blockers",
                "assignments": [
                    {"blocker": blocker.instance_id, "attacker": attacker.instance_id}
                ],
            },
            actor_id="bob",
        )
        assert attacker.blocked_by == [blocker.instance_id]


class TestConcede:
    def test_conceding_ends_a_two_player_game(self):
        session = make_game()
        keep_all(session)
        view = session.concede("bob")
        state = session.engine.state
        assert state.players[1].has_lost is True
        assert state.players[1].loss_reason == "conceded"
        assert state.game_over is True
        assert state.winner_id == "ann"
        assert view["state"]["game_over"] is True

    def test_a_two_player_concession_leaves_the_board_standing(self):
        # Nothing to sweep: with one living player the game is over, so the
        # final position stays intact for the end-of-match review.
        session = make_game()
        keep_all(session)
        session.concede("bob")
        assert session.engine.state.pending_leave_ids == []

    def test_conceding_during_setup_stops_blocking_the_table(self):
        session = make_game()
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id="ann")
        session.concede("bob")
        assert session.view(perspective="ann")["setup"]["complete"] is True

    def test_conceding_is_undoable(self):
        session = make_game()
        keep_all(session)
        session.concede("bob")
        session.rewind(1)
        assert session.engine.state.game_over is False
        assert session.engine.state.players[1].has_lost is False


class TestDeferredLeave:
    """RULE 800.4a, deferred to the next turn (see `RulesEngine.concede`)."""

    def _three_player_game(self):
        manager = GameSessionManager()
        deck = [land()] * 30
        session = manager.create_multiplayer(
            [
                {"player_id": p, "name": p.title(), "library": list(deck)}
                for p in ("ann", "bob", "cid")
            ]
        )
        for pid in ("ann", "bob", "cid"):
            session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
        return session

    def test_board_survives_until_the_next_turn_begins(self):
        session = self._three_player_game()
        state = session.engine.state
        from mtg_analyzer.models.game_object import GameObject, Zone

        obj = GameObject(bear("Bob's Bear"), owner_id="bob", zone=Zone.BATTLEFIELD)
        obj.controller_id = "bob"
        state.add_to_battlefield(obj)

        session.concede("bob")
        assert state.game_over is False  # ann and cid are still playing
        assert state.pending_leave_ids == ["bob"]
        assert obj in state.battlefield  # still standing, mid-turn

        advance_until(session, turn=2)
        assert session.engine.state.pending_leave_ids == []
        assert all(o.owner_id != "bob" for o in session.engine.state.battlefield)

    def test_a_conceded_player_is_skipped_in_turn_order(self):
        session = self._three_player_game()
        session.concede("bob")
        advance_until(session, turn=2)
        assert session.engine.state.active_player.id == "cid"


class TestPriority:
    """RULE 117: priority is genuinely passed around a shared table."""

    def _playing(self, **kwargs):
        session = make_game(**kwargs)
        keep_all(session)
        return session

    def test_the_active_player_holds_priority_once_setup_ends(self):
        session = self._playing()
        # Keeping the last hand runs the game into its first priority window
        # (untap gives nobody priority, so it can't stop there).
        state = session.engine.state
        assert state.current_step == "upkeep"
        assert state.priority_player.id == "ann"
        assert session.view(perspective="ann")["priority"] == {
            "interactive": True,
            "player_id": "ann",
            "passed": [],
        }

    def test_passing_hands_priority_to_the_next_player_in_turn_order(self):
        session = self._playing()
        session.apply_action({"type": "pass_priority"}, actor_id="ann")
        state = session.engine.state
        assert state.priority_player.id == "bob"
        assert state.current_step == "upkeep"  # nothing has ended yet
        assert session.view(perspective="bob")["priority"]["passed"] == ["ann"]

    def test_the_step_ends_only_when_everyone_has_passed(self):
        session = self._playing()
        session.apply_action({"type": "pass_priority"}, actor_id="ann")
        assert session.engine.state.current_step == "upkeep"
        session.apply_action({"type": "pass_priority"}, actor_id="bob")
        # RULE 117.4: all passed on an empty stack → the step ends, and the
        # active player gets priority again in the next one.
        assert session.engine.state.current_step == "draw"
        assert session.engine.state.priority_player.id == "ann"

    def test_a_player_without_priority_cannot_pass(self):
        session = self._playing()
        with pytest.raises(GameActionError):
            session.apply_action({"type": "pass_priority"}, actor_id="bob")

    def test_a_player_without_priority_is_offered_nothing(self):
        session = self._playing(library=[land()] * 30)
        advance_until(session, step="main1")
        assert session.engine.state.priority_player.id == "ann"
        assert any(a["type"] == "play_land" for a in session.legal_actions("ann"))
        assert session.legal_actions("bob") == []

    def test_declaring_blockers_does_not_need_priority(self):
        # RULE 509.1a is a turn-based action, not something taken with
        # priority — the attacking player still holds it while blocks are
        # declared, so the defender must still be offered them.
        from mtg_analyzer.models.game_object import GameObject, Zone

        session = self._playing(library=[land()] * 30)
        state = session.engine.state
        attacker = GameObject(bear("Attacker"), owner_id="ann", zone=Zone.BATTLEFIELD)
        attacker.controller_id, attacker.summoning_sick = "ann", False
        blocker = GameObject(bear("Blocker"), owner_id="bob", zone=Zone.BATTLEFIELD)
        blocker.controller_id, blocker.summoning_sick = "bob", False
        state.add_to_battlefield(attacker)
        state.add_to_battlefield(blocker)

        advance_until(session, step="declare_attackers")
        session.apply_action(
            {"type": "attack", "instance_ids": [attacker.instance_id]}, actor_id="ann"
        )
        advance_until(session, step="declare_blockers")
        assert session.engine.state.priority_player.id == "ann"
        assert [a["type"] for a in session.legal_actions("bob")] == ["declare_blockers"]

    def test_a_non_holder_is_refused_even_if_it_posts_the_action_anyway(self):
        # `legal_actions` filtering is a hint to the UI; the rule itself has
        # to hold where actions arrive, or a client could post one it was
        # never offered.
        session = self._playing(library=[land()] * 30)
        advance_until(session, step="main1")
        land_action = next(a for a in session.legal_actions("ann") if a["type"] == "play_land")
        session.apply_action({"type": "pass_priority"}, actor_id="ann")

        assert session.engine.state.priority_player.id == "bob"
        assert session.legal_actions("ann") == []
        with pytest.raises(GameActionError):
            session.apply_action(land_action, actor_id="ann")

    def test_acting_reclaims_priority_and_voids_earlier_passes(self):
        # RULE 117.3c: taking an action changes the game state, so the taker
        # gets priority back and every pass so far is void — the opponent
        # must get a fresh chance to respond to what just happened.
        session = self._playing(library=[land()] * 30)
        advance_until(session, step="main1")
        session.apply_action({"type": "pass_priority"}, actor_id="ann")
        assert session.engine.state.priority_passed == {"ann"}

        session.apply_action({"type": "pass_priority"}, actor_id="bob")
        # Both passed on an empty stack, so main1 ended (RULE 117.4) — the
        # active player holds priority again in the next step, freshly.
        state = session.engine.state
        assert state.current_step == "begin_combat"
        assert state.priority_player.id == "ann"
        assert state.priority_passed == set()

    def test_playing_a_land_keeps_priority_with_its_player(self):
        session = self._playing(library=[land()] * 30)
        advance_until(session, step="main1")
        land_action = next(a for a in session.legal_actions("ann") if a["type"] == "play_land")
        session.apply_action(land_action, actor_id="ann")
        state = session.engine.state
        assert state.priority_player.id == "ann"
        assert state.priority_passed == set()
        assert state.current_step == "main1"

    def test_solo_sessions_still_auto_drain(self):
        # The whole priority loop is opt-in: a goldfish session has nobody
        # to pass to and must keep resolving the stack the moment it can.
        manager = GameSessionManager()
        session = manager.create_goldfish(library=[land()] * 30)
        assert session.interactive_priority is False
        assert session.engine.interactive_priority is False
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []})
        session.apply_action({"type": "advance_step"})  # still allowed
        assert session.view()["priority"]["interactive"] is False

    def test_priority_survives_a_rewind(self):
        session = self._playing()
        session.apply_action({"type": "pass_priority"}, actor_id="ann")
        assert session.engine.state.priority_player.id == "bob"
        session.rewind(1)
        assert session.engine.interactive_priority is True
        assert session.engine.state.priority_player.id == "ann"
