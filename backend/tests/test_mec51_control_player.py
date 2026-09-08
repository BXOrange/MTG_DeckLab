"""MEC-51 (RULE 720) — one player controls another player's turn / combat.

Covers the `GameState.TurnControl` state machine, the `control_player`
effect, the hand-authored cards (Mindslaver / Worst Fears / Sorin Markov /
Emrakul / Secret of Bloodbending), and the `GameSession` routing that lets
the controller act *as* the controlled seat (priority, pending choices,
hand reveal) while a window is active.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import TurnControl
from mtg_analyzer.services.game_session import GameActionError, GameSessionManager


def _deck(n=40):
    return [Card(id=f"L{i}", name="Forest", type_line="Basic Land — Forest",
                 is_land=True) for i in range(n)]


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", _deck()), ("p2", "B", _deck())], starting_life=20, starting_hand=3
    )
    eng.start()
    return eng, eng.state


def _run_to_controlled_turn(eng, controlled="p2", limit=120):
    st = eng.state
    for _ in range(limit):
        if (st.active_player.id == controlled and st.turn_controls
                and st.turn_controls[0].phase == "active"):
            return
        if eng.advance_step() is None:
            break
    raise AssertionError("never reached the controlled player's active turn")


# --- state machine ------------------------------------------------------


def test_control_waits_then_activates_on_the_controlled_players_next_turn():
    eng, st = _engine()
    st.turn_controls.append(TurnControl("p2", "p1", st.internal_turn.number, "turn", "Mindslaver"))
    assert st.decider_for("p2") == "p2"            # still waiting
    assert st.driving_seat_for("p1") is None

    _run_to_controlled_turn(eng)

    assert st.turn_controls[0].phase == "active"
    assert st.decider_for("p2") == "p1"            # routed to the controller
    assert st.driving_seat_for("p1") == "p2"
    assert st.decider_for("p1") == "p1"            # controller's own decisions unchanged


def test_control_expires_after_the_controlled_turn():
    eng, st = _engine()
    st.turn_controls.append(TurnControl("p2", "p1", st.internal_turn.number, "turn", "Mindslaver"))
    _run_to_controlled_turn(eng)
    controlled_turn = st.internal_turn.number
    for _ in range(120):
        if eng.advance_step() is None:
            break
        if st.internal_turn.number > controlled_turn and not st.turn_controls:
            break
    assert st.turn_controls == []
    assert st.decider_for("p2") == "p2"


def test_combat_scope_only_routes_during_the_combat_phase():
    eng, st = _engine()
    tc = TurnControl("p2", "p1", st.internal_turn.number, "combat", "Secret of Bloodbending")
    st.turn_controls.append(tc)
    _run_to_controlled_turn(eng)
    # p2's turn, but we may be in a main phase — route only in combat
    saw_routed = saw_unrouted = False
    for _ in range(30):
        if st.active_player.id != "p2":
            break
        if st.current_phase == "combat":
            saw_routed = st.decider_for("p2") == "p1"
        else:
            saw_unrouted = st.decider_for("p2") == "p2"
        if eng.advance_step() is None:
            break
    assert saw_routed and saw_unrouted


def test_emrakul_grant_extra_turn_after_queues_the_controlled_players_extra_turn():
    eng, st = _engine()
    tc = TurnControl("p2", "p1", st.internal_turn.number, "turn", "Emrakul, the Promised End")
    tc.grant_extra_turn_after = True
    st.turn_controls.append(tc)
    _run_to_controlled_turn(eng)
    controlled_turn = st.internal_turn.number
    # play through the rest of p2's controlled turn
    for _ in range(120):
        if eng.advance_step() is None or st.internal_turn.number > controlled_turn:
            break
    # the extra turn was queued for p2 at that turn's end
    assert "p2" in st.extra_turns or st.active_player.id == "p2"


# --- catalogue --------------------------------------------------------


def test_all_five_cards_bind_a_control_player_effect():
    cards = {
        "Mindslaver": "Legendary Artifact",
        "Worst Fears": "Sorcery",
        "Sorin Markov": "Legendary Planeswalker — Sorin",
        "Emrakul, the Promised End": "Legendary Creature — Eldrazi",
        "Secret of Bloodbending": "Sorcery — Lesson",
    }
    for name, tl in cards.items():
        specs = ac.specs_for(Card(id=name[:6], name=name, type_line=tl))
        assert any(
            e.type == "control_player" for s in specs for e in s.effects
        ), name


def test_mindslaver_activation_installs_a_turn_control():
    eng, st = _engine()
    st.current_step = "main1"
    ms = GameObject(
        Card(id="MS", name="Mindslaver", type_line="Legendary Artifact",
             mana_cost_string="{6}"),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    ms.controller_id = "p1"
    ms.summoning_sick = False
    st.add_to_battlefield(ms)
    bind_from_catalogue(ms)
    st.player_by_id("p1").mana_pool.add_many({"C": 4})

    eng.activate_ability(st.player_by_id("p1"), ms, 0, targets=[st.player_by_id("p2")])
    eng.resolve_until_stable()

    assert [(tc.controller_id, tc.controlled_id) for tc in st.turn_controls] == [("p1", "p2")]
    assert ms.zone == Zone.GRAVEYARD          # sacrificed as a cost


# --- session routing -------------------------------------------------


def _mp_game():
    mgr = GameSessionManager()
    session = mgr.create_multiplayer(
        [
            {"player_id": "ann", "name": "Ann", "library": _deck()},
            {"player_id": "bob", "name": "Bob", "library": _deck()},
        ],
        mulligan_style="none",
    )
    for pid in ("ann", "bob"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
    return session


def _arm_control(session, controller, controlled):
    st = session.engine.state
    st.turn_controls.append(
        TurnControl(controlled, controller, st.internal_turn.number, "turn", "Mindslaver")
    )


def _advance_session_to_controlled_turn(session, controlled, limit=300):
    st = session.engine.state
    for _ in range(limit):
        if (st.active_player.id == controlled and st.turn_controls
                and st.turn_controls[0].phase == "active"):
            return
        holder = st.priority_player
        assert holder is not None, f"nobody holds priority at {st.current_step!r}"
        session.apply_action({"type": "pass_priority"}, actor_id=holder.id)
    raise AssertionError("session never reached the controlled turn")


def test_view_reports_acting_as_and_reveals_the_controlled_hand():
    session = _mp_game()
    _arm_control(session, controller="ann", controlled="bob")
    _advance_session_to_controlled_turn(session, "bob")

    v_ann = session.view(perspective="ann")
    assert v_ann["acting_as"] == "bob"
    bob_in_ann_view = next(p for p in v_ann["state"]["players"] if p["id"] == "bob")
    assert len(bob_in_ann_view["hand"]) == len(session.engine.state.player_by_id("bob").hand)

    v_bob = session.view(perspective="bob")
    assert v_bob["acting_as"] == "bob"           # bob still sees his own seat id
    # bob is not offered priority actions on his own controlled turn
    assert session.legal_actions("bob") == []


def test_controller_passes_priority_as_the_controlled_seat():
    session = _mp_game()
    _arm_control(session, controller="ann", controlled="bob")
    _advance_session_to_controlled_turn(session, "bob")
    st = session.engine.state
    assert st.priority_player.id == "bob"
    start_turn = st.internal_turn.number

    # Ann drives Bob's turn forward by passing "as" Bob; her own priority
    # windows during it are auto-passed.
    for _ in range(60):
        if st.internal_turn.number > start_turn:
            break
        session.apply_action({"type": "pass_priority"}, actor_id="ann")
    assert st.internal_turn.number > start_turn

    # Bob cannot act on his own controlled turn.
    with pytest.raises(GameActionError):
        session.apply_action({"type": "pass_priority"}, actor_id="bob")
