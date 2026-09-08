"""MEC-12 (cEDH staples 2) — Twinflame's Strive-scaled "choose any number
of target creatures you control. For each of them, create a token that's
a copy of that creature, except it has haste. Exile those tokens at the
beginning of the next end step."

New primitives: `CopyPermanentEffect.target_count`/`target_count_max`/
`target_optional` — a genuine per-target multi-copy (one token per chosen
target), distinct from the pre-existing `count` ("N copies of the one
target"); `ExileSpecificEffect`, the plural sibling of
`SacrificeSpecificEffect` for a delayed "exile all of these" tail.

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


def test_twinflame_copies_each_chosen_target_with_haste():
    eng = make_engine([_named("Twinflame")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 5})  # {1}{R} base + {2}{R} strive for a 2nd target = 5

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", power=2, toughness=2), controller="p1")
    wolf = obj_on_battlefield(eng.state, eng, creature("Wolf", power=3, toughness=3), controller="p1")

    twinflame = p1.hand[0]
    bind_from_catalogue(twinflame)
    eng.cast_spell(p1, twinflame, targets=[bear, wolf])
    eng.resolve_until_stable()

    assert p1.mana_pool.total() == 0

    bear_tokens = [o for o in eng.state.battlefield if o.is_token and o.card.name == "Bear"]
    wolf_tokens = [o for o in eng.state.battlefield if o.is_token and o.card.name == "Wolf"]
    assert len(bear_tokens) == 1
    assert len(wolf_tokens) == 1
    assert "haste" in bear_tokens[0].temp_keywords
    assert "haste" in wolf_tokens[0].temp_keywords


def test_twinflame_tokens_are_exiled_at_next_end_step():
    eng = make_engine([_named("Twinflame")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"R": 3})  # {2}{R} base, single target — no strive tax

    bear = obj_on_battlefield(eng.state, eng, creature("Bear", power=2, toughness=2), controller="p1")

    twinflame = p1.hand[0]
    bind_from_catalogue(twinflame)
    eng.cast_spell(p1, twinflame, targets=[bear])
    eng.resolve_until_stable()

    bear_token = next(o for o in eng.state.battlefield if o.is_token and o.card.name == "Bear")
    assert len(eng.state.delayed_triggers) == 1

    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()

    assert bear_token.zone == Zone.EXILE
    assert bear in eng.state.battlefield  # the real Bear is untouched
