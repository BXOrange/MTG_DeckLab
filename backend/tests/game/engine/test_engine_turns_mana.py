"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""

import pytest

from mtg_analyzer.game.phases import default_turn_sequence


from engine_test_helpers import land, make_engine, obj_on_battlefield, _dual_land


def test_turn_structure_order():
    seq = default_turn_sequence()
    step_names = [step.name for _, step in seq.iter_steps()]
    assert step_names[:4] == ["untap", "upkeep", "draw", "main1"]
    assert step_names[-1] == "cleanup"


def test_first_player_skips_first_draw_in_multiplayer():
    eng = make_engine([land()] * 30, [land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()  # turn 1, p1 active
    # No draw on turn 1 for the starting player, but a land may be played
    # from an (empty) hand — with hand=0, library is only touched by draw.
    assert len(p1.library) == before


def test_solo_player_draws_on_turn_one():
    eng = make_engine([land()] * 30, hand=0)
    p1 = eng.state.player_by_id("p1")
    before = len(p1.library)
    eng.run_turn()
    assert len(p1.library) == before - 1


def test_one_land_per_turn():
    eng = make_engine([land(), land()], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    first, second = p1.hand[0], p1.hand[1]
    eng.play_land(p1, first)
    assert not eng.can_play_land(p1, second)
    with pytest.raises(ValueError):
        eng.play_land(p1, second)


def test_tap_land_for_mana():
    eng = make_engine([land("Forest")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest = eng.play_land(p1, p1.hand[0])
    produced = eng.tap_for_mana(p1, forest)
    assert produced == {"G": 1}
    assert p1.mana_pool.pool["G"] == 1
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, forest)


def test_dual_land_taps_for_only_the_chosen_color():
    # Regression: tapping a WU dual must add ONE colour, not both.
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    p1 = eng.state.active_player
    produced = eng.tap_for_mana(p1, dual, option_index=1)  # choose U
    assert produced == {"U": 1}
    assert p1.mana_pool.pool == {"C": 0, "W": 0, "U": 1, "B": 0, "R": 0, "G": 0}


def test_tap_rejects_out_of_range_option():
    eng = make_engine([land("Forest")], hand=0)
    dual = obj_on_battlefield(eng.state, eng, _dual_land())
    with pytest.raises(ValueError):
        eng.tap_for_mana(eng.state.active_player, dual, option_index=5)


def test_legal_actions_lists_tap_options_per_source():
    eng = make_engine([land("Forest")], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj_on_battlefield(eng.state, eng, _dual_land())
    tap = next(a for a in eng.legal_actions(eng.state.active_player) if a["type"] == "tap_for_mana")
    mana = [opt["mana"] for opt in tap["options"]]
    assert mana == [{"W": 1}, {"U": 1}]
