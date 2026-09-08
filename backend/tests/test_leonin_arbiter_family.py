"""MEC-35 — Leonin Arbiter. "Players can't search libraries. Any player
may pay {2} for that player to ignore this effect until end of turn."
Widens the already-shipped `GrantSearchProhibitedEffect` (Stranglehold's
own "opponents"-scoped effect type) with a new `scope="all"`, and builds
the RULE 116.2a "any player may pay a cost, any time, for a personal
exemption" special action from scratch (`GameEngine.pay_search_exemption`),
mirroring the already-shipped `turn_face_up` special action's own shape.

Reference: docs/implementation-state/Done_Backend.md "MEC-35" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine_with_arbiter():
    eng = make_engine([_named("Leonin Arbiter")], [creature("Bear")], hand=1)
    p1 = eng.state.active_player
    arbiter = p1.hand[0]
    bind_from_catalogue(arbiter)
    p1.hand.remove(arbiter)
    from mtg_analyzer.models.game_object import Zone

    arbiter.zone = Zone.BATTLEFIELD
    eng.state.add_to_battlefield(arbiter)
    eng.recompute_continuous_effects()
    return eng, p1, eng.state.player_by_id("p2")


def test_leonin_arbiter_prohibits_every_player_including_its_controller():
    eng, p1, p2 = _engine_with_arbiter()

    eng.rules.request_search(p1, "Creature", "hand", count=1)
    assert eng.state.pending_choice is None

    eng.rules.request_search(p2, "Creature", "hand", count=1)
    assert eng.state.pending_choice is None


def test_paying_the_exemption_lets_only_that_player_search_this_turn():
    eng, p1, p2 = _engine_with_arbiter()
    p1.mana_pool.add_many({"C": 2})

    own_bear = obj_on_battlefield(eng.state, eng, creature("OwnBear"), controller="p1")
    eng.state.battlefield.remove(own_bear)
    from mtg_analyzer.models.game_object import Zone

    own_bear.zone = Zone.LIBRARY
    p1.library.append(own_bear)

    eng.pay_search_exemption(p1)
    assert p1.mana_pool.total() == 0

    eng.rules.request_search(p1, "Creature", "hand", count=1)
    assert eng.state.pending_choice is not None
    eng.state.pending_choice = None  # leave it unresolved for this check

    eng.rules.request_search(p2, "Creature", "hand", count=1)
    assert eng.state.pending_choice is None


def test_exemption_action_only_offered_while_prohibited_and_affordable():
    eng, p1, p2 = _engine_with_arbiter()
    assert eng.pay_search_exemption_actions(p1) == []  # no mana yet

    p1.mana_pool.add_many({"C": 2})
    actions = eng.pay_search_exemption_actions(p1)
    assert len(actions) == 1 and actions[0]["type"] == "pay_search_exemption"

    eng.pay_search_exemption(p1)
    assert eng.pay_search_exemption_actions(p1) == []  # already exempt this turn
