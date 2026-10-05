"""MEC-12 (cEDH staples 2) — Solitude's ETB exile + life-for-the-exiled-
creature's-controller clause.

New primitive: `GainLifeEffect.recipient="target_controller"` — reads the
same shared exile target `amount_from_target_power` already reads (RULE
608.2, one target requirement shared by both effects in the trigger), but
for *who* receives the life rather than how much.

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


def test_solitude_exiles_and_grants_life_to_the_exiled_creatures_controller():
    card = _named("Solitude")
    eng = make_engine([card], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 5})

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", power=4, toughness=4), controller="p2")
    bind_from_catalogue(bear)
    p2 = eng.state.player_by_id("p2")
    p2.life = 20

    solitude = p1.hand[0]
    bind_from_catalogue(solitude)
    eng.cast_spell(p1, solitude)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending is not None
    opt = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(opt["id"])

    assert bear.zone == Zone.EXILE
    assert p2.life == 24  # gained life equal to the exiled creature's own power


def test_solitude_never_targets_itself():
    card = _named("Solitude")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 5})

    solitude = p1.hand[0]
    bind_from_catalogue(solitude)
    eng.cast_spell(p1, solitude)
    eng.resolve_until_stable()

    # No legal target on an otherwise empty board (Solitude excludes
    # itself) — the "up to one" ETB just declines automatically.
    assert eng.state.pending_choice is None
    assert solitude in eng.state.battlefield
    assert p1.life == 20
