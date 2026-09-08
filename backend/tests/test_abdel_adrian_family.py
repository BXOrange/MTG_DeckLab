"""MEC-12 (cEDH staples 2) — Abdel Adrian, Gorion's Ward's "exile any
number of other nonland permanents you control" ETB plus its mass
leaves-battlefield return.

New primitives: `ExileAnyNumberYouControlEffect` (a *selection*, not a RULE
115 target, via `RulesEngine.request_choose_objects`'s chooser with its new
`track_exiled_with=True`) and `continuous.count_selector`'s new
`exiled_with_count` kind (reading `GameObject.exiled_with_ids`'s own
length). The leaves-battlefield half reuses `ReturnAllExiledWithEffect`
verbatim (built for Parallax Wave in the same batch).

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import Zone

from tests.support.game import creature, land, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_abdel_adrian_exiles_chosen_permanents_and_makes_matching_tokens():
    eng = make_engine([_named("Abdel Adrian, Gorion's Ward")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 5})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear"), controller="p1")
    bind_from_catalogue(bear)
    elf = obj_on_battlefield(eng.state, eng, creature("Elf"), controller="p1")
    bind_from_catalogue(elf)
    forest = obj_on_battlefield(eng.state, eng, land(), controller="p1")
    bind_from_catalogue(forest)

    adrian = p1.hand[0]
    bind_from_catalogue(adrian)
    eng.cast_spell(p1, adrian)
    eng.resolve_until_stable()

    # Only Bear and Elf are offered — the land is excluded ("nonland"),
    # Abdel Adrian itself is excluded ("other").
    pending = eng.state.pending_choice
    assert pending is not None and pending["kind"] == "choose_objects"
    offered_ids = {o["instance_id"] for o in pending["options"] if "instance_id" in o}
    assert offered_ids == {bear.instance_id, elf.instance_id}

    eng.resolve_pending_choice(bear.instance_id)
    eng.resolve_pending_choice(elf.instance_id)  # both candidates taken — the loop closes itself
    eng.resolve_until_stable()

    assert bear.zone == Zone.EXILE
    assert elf.zone == Zone.EXILE
    assert forest.zone == Zone.BATTLEFIELD
    assert adrian.exiled_with_ids == [bear.instance_id, elf.instance_id]

    soldiers = [o for o in eng.state.battlefield if o.card.name == "Soldier"]
    assert len(soldiers) == 2
    assert all((s.power, s.toughness) == (1, 1) for s in soldiers)
    assert all(s.controller_id == "p1" for s in soldiers)


def test_abdel_adrian_leaving_returns_every_exiled_permanent():
    eng = make_engine([_named("Abdel Adrian, Gorion's Ward")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 5})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear"), controller="p1")
    bind_from_catalogue(bear)

    adrian = p1.hand[0]
    bind_from_catalogue(adrian)
    eng.cast_spell(p1, adrian)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    eng.resolve_pending_choice(bear.instance_id)  # only candidate — the loop closes itself
    eng.resolve_until_stable()
    assert bear.zone == Zone.EXILE

    eng.rules.put_into_graveyard(adrian)
    eng.resolve_until_stable()

    assert bear.zone == Zone.BATTLEFIELD
    assert bear.controller_id == "p1"
    assert adrian.exiled_with_ids == []
