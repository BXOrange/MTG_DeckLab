"""BUG-21: RULE 510.4 -- who deals regular combat damage is fixed by the first step, not by the
keywords held when the regular step begins.

In the second combat damage step, a creature deals damage if it did not have first strike or double
strike as the first step began, or if it currently has double strike. The record is the exact
(instance_id, zone_incarnation) visits of GameState.first_strike_step_combatants (BUG-20).
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import MULTIPLAYER, GameSession

from tests.test_bug20_first_strike_damage_step import (
    FIRST_STRIKE_STEP,
    START_LIFE,
    _attack,
    _engine,
    _life,
    _pass_round,
    _put,
)

GIANT_POWER = 3  # Hill Giant


def _card(name):
    return CardDatabase(DB_PATH).get_card(name)


def _lord_and_giant(eng):
    """Bloodmark Mentor ("Red creatures you control have first strike") and a red Hill Giant."""
    lord = _put(eng, _card("Bloodmark Mentor"))
    giant = _put(eng, _card("Hill Giant"))
    eng.recompute_continuous_effects()
    assert "first_strike" in giant.granted_keywords
    return lord, giant


def _kill(eng, obj):
    eng.rules.put_into_graveyard(obj)
    eng.recompute_continuous_effects()


def _to_first_strike_window(eng):
    assert eng.advance_step() == ("combat", FIRST_STRIKE_STEP)


def test_lord_dying_in_the_window_does_not_give_the_unblocked_attacker_a_second_hit():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    _attack(eng, giant)
    _to_first_strike_window(eng)
    assert _life(eng) == START_LIFE - GIANT_POWER
    _kill(eng, lord)
    assert "first_strike" not in giant.granted_keywords
    eng.advance_step()
    assert _life(eng) == START_LIFE - GIANT_POWER, "a first striker that lost it deals no regular damage"


def test_lord_blocked_and_killed_in_the_first_step_leaves_the_unblocked_attacker_one_hit():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    knight = _put(eng, _card("White Knight"), "p2")  # 2/2 first strike
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.declare_attackers(p1, [lord, giant])
    eng.advance_step()
    eng.declare_blockers(p2, [{"blocker": knight, "attacker": lord}])
    _to_first_strike_window(eng)
    assert lord not in eng.state.battlefield, "the lord died to the first-strike block"
    assert _life(eng) == START_LIFE - GIANT_POWER
    eng.advance_step()
    assert _life(eng) == START_LIFE - GIANT_POWER, "without its lord the giant does not strike again"


def test_ordinary_creature_gaining_first_strike_after_the_step_still_deals_regular_damage():
    eng = _engine()
    ds = _put(eng, _card("Kwende, Pride of Femeref"))
    bear = _put(eng, _card("Grizzly Bears"))
    p1 = eng.state.player_by_id("p1")
    eng.declare_attackers(p1, [ds, bear])
    eng.advance_step()
    eng.declare_blockers(eng.state.player_by_id("p2"), [])
    _to_first_strike_window(eng)
    assert _life(eng) == START_LIFE - 2, "only Kwende's double strike has hit"
    bear.temp_keywords.add("first_strike")
    eng.recompute_continuous_effects()
    assert "first_strike" in bear.granted_keywords
    eng.advance_step()
    # Kwende second hit (2) + the ordinary bear's only hit (2); the bear, now a first striker
    # by keyword, is not in the record and so is still eligible.
    assert _life(eng) == START_LIFE - 2 - 2 - 2


def test_first_striker_gaining_double_strike_between_the_steps_deals_again():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    _attack(eng, giant)
    _to_first_strike_window(eng)
    assert _life(eng) == START_LIFE - GIANT_POWER
    _put(eng, _card("Kwende, Pride of Femeref"))  # first strikers you control have double strike
    eng.recompute_continuous_effects()
    assert "double_strike" in giant.granted_keywords
    eng.advance_step()
    assert _life(eng) == START_LIFE - 2 * GIANT_POWER


def test_creature_put_onto_the_battlefield_attacking_after_the_step_deals_regular_damage():
    eng = _engine()
    ds = _put(eng, _card("Kwende, Pride of Femeref"))
    late = _put(eng, _card("Grizzly Bears"))
    _attack(eng, ds)
    _to_first_strike_window(eng)
    assert _life(eng) == START_LIFE - 2
    assert eng.rules.put_onto_battlefield_attacking(late)
    eng.advance_step()
    assert _life(eng) == START_LIFE - 2 - 2 - 2, "Kwende's second hit plus the late attacker's hit"


def test_a_creature_that_left_and_returned_is_a_new_object_and_deals_regular_damage():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    _attack(eng, giant)
    _to_first_strike_window(eng)
    assert (giant.instance_id, giant.zone_incarnation) in eng.state.first_strike_step_combatants
    _kill(eng, lord)
    giant.zone_incarnation += 1  # RULE 400.7: a new object that happens to share the instance id
    eng.advance_step()
    assert _life(eng) == START_LIFE - 2 * GIANT_POWER


def test_no_first_strike_step_means_everyone_deals_regular_damage():
    eng = _engine()
    giant = _put(eng, _card("Hill Giant"))
    _attack(eng, giant)
    eng.advance_step()
    assert eng.state.first_strike_step_combatants is None
    assert _life(eng) == START_LIFE - GIANT_POWER


def test_record_survives_clone_between_the_steps():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    _attack(eng, giant)
    _to_first_strike_window(eng)
    cursor = eng.step_cursor
    restored = GameEngine(eng.state.clone())
    restored.resume_at(cursor)
    rlord = next(o for o in restored.state.battlefield if o.instance_id == lord.instance_id)
    _kill(restored, rlord)
    restored.advance_step()
    assert restored.state.player_by_id("p2").life == START_LIFE - GIANT_POWER
    assert _life(eng) == START_LIFE - GIANT_POWER, "the original is untouched"


def test_session_undo_between_the_steps_keeps_the_record():
    eng = _engine()
    lord, giant = _lord_and_giant(eng)
    _attack(eng, giant)
    session = GameSession(eng, mode=MULTIPLAYER)
    _pass_round(session)  # declare_blockers window
    st = session.engine.state
    assert st.current_step == FIRST_STRIKE_STEP
    _pass_round(session)  # first-strike window
    assert session.engine.state.current_step == "combat_damage"
    assert _life(session.engine) == START_LIFE - GIANT_POWER, "a pure first striker deals once"
    session.rewind(1)
    st = session.engine.state
    assert st.current_step == FIRST_STRIKE_STEP
    assert st.first_strike_step_combatants == [
        (o.instance_id, o.zone_incarnation) for o in st.battlefield if o.name == "Hill Giant"
    ]
