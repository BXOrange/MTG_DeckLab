"""MEC-12 (cEDH Rocco/staples/staples 2) — Aven Mindcensor's RULE
701.19a-adjacent search narrowing (`GrantSearchLimitedToTopNEffect`,
`RulesEngine._search_zone_objects`).

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _library_cards(n, prefix="Card"):
    return [
        Card(id=f"{prefix}{i}", name=f"{prefix}{i}", type_line="Creature — Bear",
             mana_cost_string="{1}", converted_mana_cost=1, is_creature=True, power=1, toughness=1)
        for i in range(n)
    ]


def test_opponent_search_is_limited_to_top_four():
    eng = make_engine(_library_cards(3, "P1Card"), _library_cards(10, "P2Card"), hand=0)
    p2 = eng.state.player_by_id("p2")
    mindcensor = obj_on_battlefield(eng.state, eng, _named("Aven Mindcensor"), controller="p1")
    bind_from_catalogue(mindcensor)

    # The library-construction order is preserved; the *top* of the deck is
    # the list end (`.pop()`'s own convention) — only the last 4 are eligible.
    named_top_four = {c.card.name for c in p2.library[-4:]}

    eng.rules._request_search(p2, criteria="", destination="hand")
    pending = eng.state.pending_choice
    assert pending is not None
    offered = {o["label"] for o in pending["options"] if o.get("instance_id") is not None}
    assert offered <= named_top_four
    assert len(offered) == 4


def test_own_search_is_not_limited():
    eng = make_engine(_library_cards(10, "P1Card"), hand=0)
    p1 = eng.state.player_by_id("p1")
    mindcensor = obj_on_battlefield(eng.state, eng, _named("Aven Mindcensor"), controller="p1")
    bind_from_catalogue(mindcensor)

    eng.rules._request_search(p1, criteria="", destination="hand")
    pending = eng.state.pending_choice
    assert pending is not None
    offered = {o["label"] for o in pending["options"] if o.get("instance_id") is not None}
    assert len(offered) == 10
