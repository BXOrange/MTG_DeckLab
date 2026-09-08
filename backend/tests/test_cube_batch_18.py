"""cEDH staples cube — batch 18: the extra-turn primitive (RULE 500.7).

New core capability: `GameState.extra_turns` (a FIFO of player ids) +
`TakeExtraTurnEffect`; `GameEngine.begin_turn` pops the queue instead of
rotating the round-robin, so an extra turn is taken right after the current
one (RULE 500.7). Final Fortune's "at the beginning of that turn's end step,
you lose the game" downside reuses the batch-22 delayed-trigger primitive with
``min_turn_offset=1`` so it fires at the *extra* turn's end step, not the
current turn's.

Registers Final Fortune. Time Warp / Last Chance aren't in this cache but share
the `take_extra_turn` primitive.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue as ac
from mtg_analyzer.game.effects.core import CreateDelayedTriggerEffect, TakeExtraTurnEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _src(controller="p1") -> GameObject:
    obj = GameObject(Card(id="ff", name="Final Fortune", type_line="Instant"),
                     owner_id=controller, zone=Zone.GRAVEYARD)
    obj.controller_id = controller
    return obj


def _two_player_engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )


# ---------------------------------------------------------------------------
# 1. The extra-turn queue
# ---------------------------------------------------------------------------


def test_begin_turn_takes_a_queued_extra_turn_before_rotating():
    eng = _two_player_engine()
    eng.begin_turn()  # turn 1 → p1
    assert eng.state.active_player.id == "p1"
    eng.state.extra_turns.append("p1")
    eng.begin_turn()  # would normally rotate to p2 — takes p1's extra turn
    assert eng.state.active_player.id == "p1"
    assert eng.state.extra_turns == []
    eng.begin_turn()  # queue empty now → normal rotation to p2
    assert eng.state.active_player.id == "p2"


def test_take_extra_turn_effect_queues_the_controller():
    eng = _two_player_engine()
    eng.begin_turn()
    eff = TakeExtraTurnEffect()
    eff.source = _src("p1")
    eff.apply(eng.rules.context)
    assert eng.state.extra_turns == ["p1"]


# ---------------------------------------------------------------------------
# 2. Registration
# ---------------------------------------------------------------------------


def test_final_fortune_registered_and_specs():
    assert "final fortune" in ac._REGISTRY
    specs = ac._REGISTRY["final fortune"]()
    types = {e.type for s in specs for e in s.effects}
    assert "take_extra_turn" in types
    assert "create_delayed_trigger" in types


# ---------------------------------------------------------------------------
# 3. Full integration: extra turn taken, loss deferred to *its* end step
# ---------------------------------------------------------------------------


def test_final_fortune_grants_extra_turn_and_loses_at_its_end_step():
    eng = _two_player_engine()
    eng.start()  # turn 1, p1
    while eng.state.current_step != "main1":
        eng.advance_step()
    assert eng.state.internal_turn.number == 1

    src = _src("p1")
    take = TakeExtraTurnEffect(); take.source = src
    take.apply(eng.rules.context)
    arm = CreateDelayedTriggerEffect(
        step="end", scope="controller", min_turn_offset=1,
        effects=[{"type": "lose_game", "params": {"reason": "final_fortune"}}],
        source=src,
    )
    arm.apply(eng.rules.context)
    assert eng.state.extra_turns == ["p1"]

    p1 = eng.state.player_by_id("p1")
    turn2_active = None
    loss_turn = None
    for _ in range(40):
        if eng.state.game_over:
            break
        eng.advance_step()
        if eng.state.internal_turn.number == 2 and turn2_active is None:
            turn2_active = eng.state.active_player.id
        if p1.has_lost and loss_turn is None:
            loss_turn = eng.state.internal_turn.number
            break

    assert turn2_active == "p1", "the extra turn (turn 2) is p1's, not p2's"
    assert p1.has_lost, "the delayed 'you lose the game' fired"
    assert loss_turn == 2, "loss fired at the EXTRA turn's end step, not turn 1's"


def test_final_fortune_does_not_lose_on_the_casting_turns_end_step():
    """min_turn_offset must skip the current turn's end step."""
    eng = _two_player_engine()
    eng.start()
    while eng.state.current_step != "main1":
        eng.advance_step()

    src = _src("p1")
    arm = CreateDelayedTriggerEffect(
        step="end", scope="controller", min_turn_offset=1,
        effects=[{"type": "lose_game", "params": {"reason": "final_fortune"}}],
        source=src,
    )
    arm.apply(eng.rules.context)
    p1 = eng.state.player_by_id("p1")

    # Walk to the end of turn 1 only.
    while not (eng.state.internal_turn.number == 1 and eng.state.current_step == "end"):
        eng.advance_step()
    eng.advance_step()  # run past turn 1's end step
    assert not p1.has_lost, "no extra turn was queued and turn 1's end must not fire it"
