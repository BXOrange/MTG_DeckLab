"""MEC-12 (cEDH staples 2) — Soul Partition's "exile target nonland
permanent, its owner may play it, taxed {2} more for an opponent" clause.

New primitives: `ExileEffect.grant_owner_play_permission`/`owner_play_
permission_tax` — the standing sibling of Lukka, Coppercoat Outcast's own
board-gated `GameState.exile_cast_condition` grant, keyed to the exiled
card's owner rather than the exiling spell's caster, plus a per-instance
cost tax read by `continuous.self_cost_reduction_for`'s new `caster_id`
param. Also exercises the real latent bug this batch found and fixed:
`legal_actions`'s exile-zone offer list never checked `_has_conditional_
exile_permission` at all.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game_object import Zone

from tests.test_game_engine import creature, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_soul_partition_grants_only_the_owner_a_taxed_play_permission():
    eng = make_engine([_named("Soul Partition")], [creature("Bear", cost="{1}{G}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p2 = eng.state.player_by_id("p2")
    p1.mana_pool.add_many({"W": 2})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", cost="{1}{G}"), controller="p2")
    bind_from_catalogue(bear)

    partition = p1.hand[0]
    bind_from_catalogue(partition)
    eng.cast_spell(p1, partition, targets=[bear])
    eng.resolve_until_stable()

    assert bear.zone == Zone.EXILE
    assert eng.state.exile_cast_condition[bear.instance_id][0] == "p2"

    # p1 (the exiler, not the owner) never has the permission — checked
    # during p1's own turn, with plenty of matching mana on hand, so
    # neither timing nor payability is what's blocking it.
    p1.mana_pool.add_many({"G": 3, "C": 3})
    assert eng.can_cast(p1, bear) is False

    # Only the owner (p2) has the permission — checked on p2's own turn,
    # with the {2} tax's own mana already in the pool, so sorcery-speed
    # timing/payability don't block it either.
    eng.state.active_player_index = 1
    p2.mana_pool.add_many({"G": 4})  # {1}{G} base + {2} tax = mana value 4
    assert eng.can_cast(p2, bear) is True

    # p2 is an opponent of p1 (the exiler) — the {2} tax applies.
    eng.cast_spell(p2, bear)
    eng.resolve_until_stable()
    assert bear in eng.state.battlefield
    assert p2.mana_pool.total() == 0  # {1}{G} base + {2} tax = 4 total spent


def test_soul_partition_self_target_has_no_tax_for_its_own_owner():
    eng = make_engine([_named("Soul Partition"), creature("OwnBear", cost="{1}{G}")], [], hand=2)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 2})

    own_bear = obj_on_battlefield(eng.state, eng, creature("OwnBear", cost="{1}{G}"), controller="p1")
    bind_from_catalogue(own_bear)

    partition = next(o for o in p1.hand if o.card.name == "Soul Partition")
    bind_from_catalogue(partition)
    eng.cast_spell(p1, partition, targets=[own_bear])
    eng.resolve_until_stable()

    assert own_bear.zone == Zone.EXILE
    assert eng.state.exile_cast_condition[own_bear.instance_id][0] == "p1"

    p1.mana_pool.add_many({"G": 2})
    eng.cast_spell(p1, own_bear)
    eng.resolve_until_stable()
    assert own_bear in eng.state.battlefield
    assert p1.mana_pool.total() == 0  # {1}{G} only — no tax against its own owner/exiler
