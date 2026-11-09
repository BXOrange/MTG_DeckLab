"""BUG-55 -- the first-turn draw skip (RULE 103.8a) covers only the turn's original draw step.

An additional beginning phase (RULE 500.8, Cyclonus, Cybertronian Fighter) on the game's first turn brings a second
draw step, which is an ordinary draw step and must draw.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSessionManager

CYCLONUS = "Cyclonus, the Saboteur // Cyclonus, Cybertronian Fighter"
LIBRARY_SIZE = 20
NO_STARTING_HAND = 0
STEP_LIMIT = 80  # a turn with an extra beginning phase is well under this many steps
SECOND_TURN = 2
THIRD_TURN = 3
TWO_PLAYER_IDS = ("p1", "p2")
THREE_PLAYER_IDS = ("p1", "p2", "p3")


def cyclonus_card():
    try:
        with sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
            row = conn.execute("SELECT data FROM cards WHERE name = ?", (CYCLONUS,)).fetchone()
    except sqlite3.Error:
        row = None
    if row is None:
        pytest.skip(f"{CYCLONUS} is not in the card cache")
    return Card.from_dict(json.loads(row[0]))


def land():
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def new_engine(ids=TWO_PLAYER_IDS):
    engine = GameEngine.new_game(
        [(pid, pid.upper(), [land()] * LIBRARY_SIZE) for pid in ids], starting_hand=NO_STARTING_HAND)
    return engine  # the first advance_step opens turn 1 through the real turn loop


def hand_size(engine, pid):
    return len(next(p for p in engine.state.players if p.id == pid).hand)


def advance_to(engine, step, turn=None):
    """Walk the real turn loop until ``step`` (of ``turn``, when given) has just been run."""
    for _ in range(STEP_LIMIT):
        ran = engine.advance_step()
        assert ran is not None, f"game stopped before {step!r}"
        if ran[1] == step and (turn is None or engine.state.internal_turn.number == turn):
            return
    raise AssertionError(f"never reached {step!r}")


def put_converted_cyclonus(engine, pid):
    """Cyclonus on the battlefield with its back face (the Vehicle) up, abilities bound."""
    obj = GameObject(cyclonus_card(), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    engine.state.battlefield.append(obj)
    bind_from_catalogue(obj)
    assert engine.rules.transform_permanent(obj)
    engine.recompute_continuous_effects()
    return obj


def cyclonus_connects(engine, obj, victim_id):
    engine.state.fire_event(GameEvent(
        EventType.DAMAGE, source_id=obj.instance_id, instance_id=obj.instance_id, target_id=victim_id, amount=2,
        combat=True, is_player=True, controller_id=obj.controller_id, player_id=victim_id))
    engine.resolve_until_stable()


def steps_until_turn_ends(engine, turn):
    """Run every remaining step of ``turn``, returning the names of the draw steps that actually executed."""
    seen_draw_steps = 0
    while engine.state.internal_turn.number == turn:
        ran = engine.advance_step()
        assert ran is not None
        if ran[1] == "draw" and engine.state.internal_turn.number == turn:
            seen_draw_steps += 1
    return seen_draw_steps


def play_turn_one_with_cyclonus(engine):
    """Turn 1 through combat, with a converted Cyclonus connecting (queueing the extra beginning phase)."""
    active = engine.state.active_player.id
    other = next(p.id for p in engine.state.players if p.id != active)
    cyclonus = put_converted_cyclonus(engine, active)
    advance_to(engine, "begin_combat")
    cyclonus_connects(engine, cyclonus, other)
    assert engine.state.pending_extra_beginning_phases == 1
    return active


def test_normal_first_turn_still_skips_the_starting_players_draw():
    engine = new_engine()
    advance_to(engine, "main1")
    assert hand_size(engine, engine.state.active_player.id) == 0  # RULE 103.8a


def test_extra_beginning_phase_on_turn_one_draws_exactly_once():
    engine = new_engine()
    active = play_turn_one_with_cyclonus(engine)
    assert hand_size(engine, active) == 0  # the original draw step was skipped
    advance_to(engine, "draw", turn=1)
    # RULE 500.8: the additional beginning phase's draw step is not the one RULE 103.8a skips.
    assert hand_size(engine, active) == 1
    steps_until_turn_ends(engine, 1)
    assert hand_size(engine, active) == 1


def test_second_players_first_turn_and_later_turns_draw_once():
    engine = new_engine()
    advance_to(engine, "untap")
    first = engine.state.active_player.id
    second = next(p.id for p in engine.state.players if p.id != first)
    steps_until_turn_ends(engine, 1)
    advance_to(engine, "main1", turn=SECOND_TURN)
    assert engine.state.active_player.id == second
    assert hand_size(engine, second) == 1
    steps_until_turn_ends(engine, SECOND_TURN)
    advance_to(engine, "main1", turn=THIRD_TURN)
    assert hand_size(engine, first) == 1  # the starting player's second turn: an ordinary draw


def test_extra_beginning_phase_on_a_later_turn_draws_normally():
    engine = new_engine()
    advance_to(engine, "untap")
    steps_until_turn_ends(engine, 1)
    advance_to(engine, "main1", turn=SECOND_TURN)
    active = engine.state.active_player.id
    assert hand_size(engine, active) == 1
    cyclonus = put_converted_cyclonus(engine, active)
    advance_to(engine, "begin_combat", turn=SECOND_TURN)
    cyclonus_connects(engine, cyclonus, next(pid for pid in TWO_PLAYER_IDS if pid != active))
    advance_to(engine, "draw", turn=SECOND_TURN)
    assert hand_size(engine, active) == 2


def test_multiplayer_pod_nobody_skips_even_on_turn_one():
    engine = new_engine(THREE_PLAYER_IDS)
    advance_to(engine, "main1")
    assert hand_size(engine, engine.state.active_player.id) == 1  # RULE 103.8c


def test_clone_in_the_middle_of_turn_one_keeps_the_skip_spent():
    engine = new_engine()
    play_turn_one_with_cyclonus(engine)
    # The tracker is plain state, so a clone (the undo/restart path) carries it and the extra draw still follows.
    assert engine.state.clone().first_turn_draw_step_skipped
    advance_to(engine, "draw", turn=1)
    assert hand_size(engine, engine.state.active_player.id) == 1


def test_a_new_turn_resets_the_tracker():
    engine = new_engine()
    advance_to(engine, "main1")
    assert engine.state.first_turn_draw_step_skipped
    steps_until_turn_ends(engine, 1)
    assert engine.state.internal_turn.number == SECOND_TURN
    assert not engine.state.first_turn_draw_step_skipped


def test_session_flow_extra_phase_on_turn_one_draws_once_and_survives_undo():
    session = GameSessionManager().create_multiplayer(
        [{"player_id": pid, "name": pid, "library": [land()] * LIBRARY_SIZE} for pid in TWO_PLAYER_IDS],
        mulligan_style="london")
    for pid in TWO_PLAYER_IDS:
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=pid)
    state = session.engine.state
    state.skip_first_draw = True
    # Seven-card opening hands: compare against the hand size before the first turn's draw step.
    active = state.active_player.id
    other = next(p for p in TWO_PLAYER_IDS if p != active)
    opening = hand_size(session.engine, active)
    cyclonus = put_converted_cyclonus(session.engine, active)

    def pass_all():
        holder = session.engine.state.priority_player
        session.apply_action({"type": "pass_priority"}, actor_id=holder.id)

    for _ in range(STEP_LIMIT):
        if session.engine.state.current_step == "begin_combat":
            break
        pass_all()
    assert hand_size(session.engine, active) == opening  # RULE 103.8a
    cyclonus_connects(session.engine, cyclonus, other)
    for _ in range(STEP_LIMIT):
        if session.engine.state.current_step == "draw":
            break
        pass_all()
    assert session.engine.state.current_step == "draw"
    assert hand_size(session.engine, active) == opening + 1
    assert session.engine.state.first_turn_draw_step_skipped
    # Undo the pass that ran the draw step: the restored state keeps the spent skip, so redoing it draws once.
    session.rewind(1)
    assert session.engine.state.first_turn_draw_step_skipped
    assert hand_size(session.engine, active) == opening
    pass_all()
    assert hand_size(session.engine, active) == opening + 1
