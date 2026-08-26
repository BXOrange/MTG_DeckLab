"""MEC-12 (cEDH staples 2) — Yawgmoth's Will's "play lands and cast spells
from your graveyard until end of turn" plus "cards would be put into your
graveyard this turn are exiled instead."

New primitives: `GraveyardPlayPermissionThisTurnEffect`/`Player.
graveyard_play_permission_until_turn` — the first graveyard-cast permission
source (of any kind) that covers lands, since it's a player-scoped grant
rather than a permanent-anchored one; `GraveyardRedirectToExileEffect`/
`Player.graveyard_redirect_to_exile_until_turn` — the player-scoped,
whole-turn sibling of the existing per-object `cast_via_graveyard_cast_
permission_until_turn` check in `RulesEngine._move_to_graveyard`.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, instant, land, make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _cast_will(hand_cards=None):
    eng = make_engine([_named("Yawgmoth's Will")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})

    will = p1.hand[0]
    bind_from_catalogue(will)
    eng.cast_spell(p1, will)
    eng.resolve_until_stable()
    return eng, p1


def test_yawgmoths_will_lets_you_play_a_land_from_your_graveyard():
    eng, p1 = _cast_will()
    forest = GameObject(land(), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(forest)

    assert eng.can_play_land(p1, forest) is True
    eng.play_land(p1, forest)
    assert forest in eng.state.battlefield


def test_yawgmoths_will_lets_you_cast_a_spell_from_your_graveyard():
    eng, p1 = _cast_will()
    bolt = GameObject(instant(), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bolt)
    p1.mana_pool.add_many({"R": 1})

    assert eng.can_cast(p1, bolt) is True
    eng.cast_spell(p1, bolt)
    assert bolt not in p1.graveyard


def test_yawgmoths_will_permission_does_not_apply_without_casting_it():
    eng = make_engine([], [], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    forest = GameObject(land(), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(forest)

    assert eng.can_play_land(p1, forest) is False


def test_yawgmoths_will_redirects_graveyard_bound_cards_to_exile():
    eng, p1 = _cast_will()
    bear = obj_on_battlefield(eng.state, eng, creature("Bear"), controller="p1")

    eng.rules.destroy(bear)

    assert bear.zone == Zone.EXILE
    assert bear not in p1.graveyard


def test_yawgmoths_will_redirect_does_not_affect_opponents_cards():
    eng = make_engine([_named("Yawgmoth's Will")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    p2 = eng.state.player_by_id("p2")

    will = p1.hand[0]
    bind_from_catalogue(will)
    eng.cast_spell(p1, will)
    eng.resolve_until_stable()

    opp_bear = obj_on_battlefield(eng.state, eng, creature("OppBear"), controller="p2")

    eng.rules.destroy(opp_bear)

    assert opp_bear.zone == Zone.GRAVEYARD
    assert opp_bear in p2.graveyard
