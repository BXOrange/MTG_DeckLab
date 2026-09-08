"""MEC-12 (cEDH staples 2) — Skyclave Apparition's ETB O-Ring exile plus its
leaves-battlefield "the exiled card's owner creates an X/X token" clause.

New primitives: `ExileEffect.max_mana_value` (the same target-offer-time cap
`DestroyEffect` already had) and `CreateTokenForLinkedExileEffect` — the
token-creating sibling of `ReturnLinkedExileEffect`, reading the same
`GameObject.linked_exile_id` link but handing off to token creation under
the *linked card's own owner* instead of returning it.

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


def test_skyclave_apparition_exiles_and_leaves_battlefield_makes_illusion_token():
    eng = make_engine([_named("Skyclave Apparition")], [creature("Bear", cost="{2}{G}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 3})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", cost="{2}{G}"), controller="p2")
    bind_from_catalogue(bear)

    apparition = p1.hand[0]
    bind_from_catalogue(apparition)
    eng.cast_spell(p1, apparition)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert bear.zone == Zone.EXILE
    assert apparition.linked_exile_id == bear.instance_id

    eng.rules.put_into_graveyard(apparition)
    eng.resolve_until_stable()

    p2 = eng.state.player_by_id("p2")
    illusions = [o for o in eng.state.battlefield if o.card.name == "Illusion"]
    assert len(illusions) == 1
    token = illusions[0]
    assert token.owner_id == "p2"
    assert token.controller_id == "p2"
    assert (token.power, token.toughness) == (3, 3)  # {2}{G} = mana value 3
    assert apparition.linked_exile_id is None


def test_skyclave_apparition_ignores_a_permanent_over_the_mana_value_cap():
    eng = make_engine([_named("Skyclave Apparition")], [creature("BigBear", cost="{5}{G}")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 3})

    big_bear = obj_on_battlefield(eng.state, eng, creature("BigBear", cost="{5}{G}"), controller="p2")
    bind_from_catalogue(big_bear)

    apparition = p1.hand[0]
    bind_from_catalogue(apparition)
    eng.cast_spell(p1, apparition)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    # Only the decline option — mana value 6 is over the cap.
    assert pending is None or all(o["id"] == "decline" for o in pending["options"])
    assert big_bear.zone == Zone.BATTLEFIELD
