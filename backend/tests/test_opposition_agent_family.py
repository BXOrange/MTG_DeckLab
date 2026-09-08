"""MEC-39 — Opposition Agent. Real printed text: "You control your
opponents while they're searching their libraries. While an opponent is
searching their library, they exile each card they find. You may play
those cards for as long as they remain exiled, and you may spend mana as
though it were mana of any color to cast them." Modeled as a search-result
redirect (a new `StaticAbility` layer, `"search_redirect"`) rather than a
genuine RULE 269.4 player-control exchange — this engine's search flow has
no other decision point a real control swap would change, so the
mechanical second paragraph already describes the whole outcome.

Reference: docs/implementation-state/Done_Backend.md "MEC-39" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _engine_with_agent():
    eng = make_engine(
        [_named("Opposition Agent")], [creature("Bear"), creature("Filler")], hand=1,
    )
    p1 = eng.state.active_player
    agent = p1.hand[0]
    bind_from_catalogue(agent)
    p1.hand.remove(agent)
    agent.zone = Zone.BATTLEFIELD
    eng.state.add_to_battlefield(agent)
    eng.recompute_continuous_effects()
    return eng, p1, eng.state.player_by_id("p2")


def test_opponent_search_redirects_the_found_card_to_exile():
    eng, p1, p2 = _engine_with_agent()

    eng.rules.request_search(p2, "Creature", "hand", count=1)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(chosen)

    found = eng.state.find_object(chosen)
    assert found in p2.exile
    assert found not in p2.hand
    assert eng.state.exile_cast_condition[chosen] == (p1.id, {})
    assert eng.state.mana_wildcard_permission[chosen] == "color"


def test_agents_own_controller_searching_is_not_redirected():
    eng, p1, p2 = _engine_with_agent()
    lib_bear = GameObject(creature("OwnBear"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(lib_bear)

    eng.rules.request_search(p1, "Creature", "hand", count=1)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(chosen)

    found = eng.state.find_object(chosen)
    assert found in p1.hand
    assert chosen not in eng.state.exile_cast_condition
