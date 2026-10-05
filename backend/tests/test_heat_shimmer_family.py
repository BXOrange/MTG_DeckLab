"""MEC-12 (cEDH staples 2) — Heat Shimmer's "create a token that's a copy
of target creature, except it has haste and 'At the beginning of the end
step, exile this token.'"

No new primitive: the single-target sibling of Twinflame's own
`create_delayed_trigger`/`exile_specific` delayed-exile shape (same batch).

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import Zone

from tests.support.game import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_heat_shimmer_copies_own_creature_with_haste():
    eng = make_engine([_named("Heat Shimmer")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 3})

    bear = obj_on_battlefield(eng.state, eng, creature("MyBear", power=2, toughness=2), controller="p1")

    shimmer = p1.hand[0]
    bind_from_catalogue(shimmer)
    eng.cast_spell(p1, shimmer, targets=[bear])
    eng.resolve_until_stable()

    token = next(o for o in eng.state.battlefield if o.is_token and o.card.name == "MyBear")
    assert "haste" in token.temp_keywords
    assert len(eng.state.delayed_triggers) == 1


def test_heat_shimmer_can_target_an_opponents_creature():
    eng = make_engine([_named("Heat Shimmer")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 3})

    opp_bear = obj_on_battlefield(eng.state, eng, creature("OppBear", power=2, toughness=2), controller="p2")

    shimmer = p1.hand[0]
    bind_from_catalogue(shimmer)
    assert eng.can_cast(p1, shimmer, targets=[opp_bear]) is True
    eng.cast_spell(p1, shimmer, targets=[opp_bear])
    eng.resolve_until_stable()

    token = next(o for o in eng.state.battlefield if o.is_token and o.card.name == "OppBear")
    assert token.controller_id == "p1"
    assert "haste" in token.temp_keywords
    assert len(eng.state.delayed_triggers) == 1

    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert token.zone == Zone.EXILE
    assert opp_bear in eng.state.battlefield
