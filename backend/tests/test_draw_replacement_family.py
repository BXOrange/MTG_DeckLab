"""MEC-32 — the draw-replacement family (Alms Collector, Notion Thief,
Chains of Mephistopheles), all three blocked on the same real architectural
gap: `RulesEngine.draw(player, count)` used to fire one independent,
hardcoded ``count=1`` `EventType.DRAW` per card, so no replacement could see
"this player is attempting to draw 2+ cards as one instruction" (Alms
Collector) or "this is the first draw in the current draw step" (Notion
Thief/Chains of Mephistopheles).

Fixed by restructuring `draw()` to fire one `EventType.DRAW_INSTRUCTION`
event for the whole call *before* splitting it into per-card `DRAW` events
(kept as its own event type so it can't double-apply an ordinary per-card
replacement), and by adding `GameState.first_draw_done_this_step`, reset as
a player's own draw step begins (`GameEngine._run_step`) and consulted by
`RulesEngine._single_draw`.

Reference: docs/implementation-state/Done_Backend.md "MEC-32" entry.
"""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.services.card_database import CardDatabase


def _named(name):
    return CardDatabase(DB_PATH).get_card(name)


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids] or [
        Player(id="p1", life=20), Player(id="p2", life=20),
    ]
    state = GameState(players=players)
    return GameEngine(state), state


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _land(name, subtype="Forest", text="{T}: Add {G}."):
    return Card(
        id=name, name=name, type_line=f"Basic Land — {subtype}", is_land=True,
        oracle_text=text,
    )


def _filler(name):
    return Card(id=name, name=name, type_line="Instant", is_instant=True, oracle_text="")


def _give_library(state, player_id, count=5):
    player = state.player_by_id(player_id)
    for i in range(count):
        player.library.append(
            GameObject(_land(f"Filler {i}"), owner_id=player_id, zone=Zone.LIBRARY)
        )


def _give_hand(state, player_id, count):
    player = state.player_by_id(player_id)
    for i in range(count):
        player.hand.append(
            GameObject(_filler(f"Hand Card {i}"), owner_id=player_id, zone=Zone.HAND)
        )


# ---------------------------------------------------------------------------
# Alms Collector — instruction-level "two or more" split
# ---------------------------------------------------------------------------


def test_alms_collector_is_registered_and_modeled():
    assert is_registered("Alms Collector")


def test_alms_collector_splits_a_two_card_draw_into_one_each():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1")
    _give_library(state, "p2")
    _bf(state, _named("Alms Collector"), controller="p1")
    engine.recompute_continuous_effects()

    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    engine.rules.draw(p2, 2)

    assert len(p2.hand) == 1
    assert len(p1.hand) == 1


def test_alms_collector_leaves_a_single_card_draw_alone():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p2")
    _bf(state, _named("Alms Collector"), controller="p1")
    engine.recompute_continuous_effects()

    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    engine.rules.draw(p2, 1)

    assert len(p2.hand) == 1
    assert len(p1.hand) == 0


def test_alms_collector_ignores_its_own_controllers_multi_draw():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1")
    _bf(state, _named("Alms Collector"), controller="p1")
    engine.recompute_continuous_effects()

    p1 = state.player_by_id("p1")
    engine.rules.draw(p1, 2)

    assert len(p1.hand) == 2


# ---------------------------------------------------------------------------
# Notion Thief — per-card, "first in draw step" exempted
# ---------------------------------------------------------------------------


def test_notion_thief_is_registered_and_modeled():
    assert is_registered("Notion Thief")


def test_notion_thief_lets_the_draw_steps_first_draw_through():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p2")
    _bf(state, _named("Notion Thief"), controller="p1")
    engine.recompute_continuous_effects()

    state.active_player_index = next(
        i for i, p in enumerate(state.players) if p.id == "p2"
    )
    state.current_step = "draw"
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    engine.rules.draw(p2, 1)

    assert len(p2.hand) == 1
    assert len(p1.hand) == 0
    assert state.first_draw_done_this_step["p2"] is True


def test_notion_thief_steals_a_second_draw_in_the_same_draw_step():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1")
    _give_library(state, "p2")
    _bf(state, _named("Notion Thief"), controller="p1")
    engine.recompute_continuous_effects()

    state.active_player_index = next(
        i for i, p in enumerate(state.players) if p.id == "p2"
    )
    state.current_step = "draw"
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    engine.rules.draw(p2, 1)  # the step's own first draw — untouched
    engine.rules.draw(p2, 1)  # a second draw in the same step — stolen

    assert len(p2.hand) == 1
    assert len(p1.hand) == 1


def test_notion_thief_steals_a_draw_outside_any_draw_step():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1")
    _give_library(state, "p2")
    _bf(state, _named("Notion Thief"), controller="p1")
    engine.recompute_continuous_effects()

    state.current_step = "main1"
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    engine.rules.draw(p2, 1)

    assert len(p2.hand) == 0
    assert len(p1.hand) == 1


def test_notion_thief_ignores_its_own_controllers_draws():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1")
    _bf(state, _named("Notion Thief"), controller="p1")
    engine.recompute_continuous_effects()

    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    engine.rules.draw(p1, 1)

    assert len(p1.hand) == 1


# ---------------------------------------------------------------------------
# Chains of Mephistopheles — table-wide, discard/draw/mill recursion
# ---------------------------------------------------------------------------


def test_chains_is_registered_and_modeled():
    assert is_registered("Chains of Mephistopheles")


def test_chains_lets_the_draw_steps_first_draw_through():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p2")
    _give_hand(state, "p2", 2)
    _bf(state, _named("Chains of Mephistopheles"), controller="p1")
    engine.recompute_continuous_effects()

    state.active_player_index = next(
        i for i, p in enumerate(state.players) if p.id == "p2"
    )
    state.current_step = "draw"
    p2 = state.player_by_id("p2")
    engine.rules.draw(p2, 1)

    assert len(p2.hand) == 3  # 2 starting + 1 drawn, no discard
    assert len(p2.graveyard) == 0


def test_chains_discards_the_whole_hand_then_mills_on_a_non_first_draw():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p2", count=5)
    _give_hand(state, "p2", 3)
    _bf(state, _named("Chains of Mephistopheles"), controller="p1")
    engine.recompute_continuous_effects()

    state.current_step = "main1"  # never "first in a draw step"
    p2 = state.player_by_id("p2")
    library_before = len(p2.library)
    engine.rules.draw(p2, 1)

    # Every one of the 3 starting hand cards is discarded (each compensating
    # "draw a card" is itself replaced again, since it's still not the
    # step's first draw), then the final, hand-empty iteration mills
    # instead of drawing (RULE 616.1f's chain terminates there) — 3
    # discards + 1 mill, all landing in the same graveyard.
    assert len(p2.hand) == 0
    assert len(p2.graveyard) == 4
    assert library_before - len(p2.library) == 1


def test_chains_applies_to_its_own_controller_too():
    engine, state = _engine("p1", "p2")
    _give_library(state, "p1", count=5)
    _give_hand(state, "p1", 1)
    _bf(state, _named("Chains of Mephistopheles"), controller="p1")
    engine.recompute_continuous_effects()

    state.current_step = "main1"
    p1 = state.player_by_id("p1")
    engine.rules.draw(p1, 1)

    assert len(p1.hand) == 0
    assert len(p1.graveyard) == 2  # 1 discard + the final mill
