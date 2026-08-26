"""MEC-12 (cEDH staples 2) — Parallax Wave's repeatable "remove a fade
counter: exile target creature" plus its mass "each player returns all
cards they own exiled with it" leaves-battlefield trigger.

New primitive: `ReturnAllExiledWithEffect`/`"return_all_exiled_with"` — the
mass sibling of the O-Ring family's `ReturnLinkedExileEffect`, reading
`GameObject.exiled_with_ids` (MEC-21's accumulating tracker) instead of the
single-slot `linked_exile_id`, since several different creatures (owned by
several different players) can be exiled by the same Parallax Wave over its
lifetime.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.game_object import Zone

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_parallax_wave_exiles_multiple_creatures_and_returns_them_all_on_leaving():
    eng = make_engine([], [], hand=0)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    wave = obj_on_battlefield(eng.state, eng, _named("Parallax Wave"), controller="p1")
    bind_from_catalogue(wave)
    wave.counters["fade"] = 5

    own_bear = obj_on_battlefield(eng.state, eng, creature("OwnBear"), controller="p1")
    bind_from_catalogue(own_bear)
    opp_bear = obj_on_battlefield(eng.state, eng, creature("OppBear"), controller="p2")
    bind_from_catalogue(opp_bear)

    eng.activate_ability(p1, wave, targets=[own_bear])
    eng.resolve_until_stable()
    eng.activate_ability(p1, wave, targets=[opp_bear])
    eng.resolve_until_stable()

    assert own_bear.zone == Zone.EXILE
    assert opp_bear.zone == Zone.EXILE
    assert wave.exiled_with_ids == [own_bear.instance_id, opp_bear.instance_id]
    assert wave.counters.get("fade", 0) == 3  # two fade counters spent

    eng.rules.put_into_graveyard(wave)
    eng.resolve_until_stable()

    assert own_bear.zone == Zone.BATTLEFIELD
    assert own_bear.controller_id == "p1"
    assert opp_bear.zone == Zone.BATTLEFIELD
    assert opp_bear.controller_id == "p2"
    assert wave.exiled_with_ids == []
