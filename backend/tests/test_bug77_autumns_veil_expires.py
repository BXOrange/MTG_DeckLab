"""BUG-77 -- Autumn's Veil's "can't be the target of blue or black spells this turn" is a RULE 514.2 "until end of turn"
effect: it refuses a blue spell this turn, expires at cleanup, and a state clone (undo) carries it consistently."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.star_trek import advance_to, game, vanilla

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="needs the local card cache")


def _spell(name, controller="p2"):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name} not in the local card cache")
    obj = GameObject(card, owner_id=controller, zone=Zone.STACK)
    obj.controller_id = controller
    return obj


def _blue_spell():
    return _spell("Unsummon")


def _red_spell():
    return _spell("Lightning Bolt")


def _veiled_bear():
    eng, p1, _ = game("Autumn's Veil", via_steps=True)
    bear = vanilla(eng, "p1")
    p1.mana_pool.add("G", 1)
    eng.cast_spell(p1, p1.hand[0])
    eng.resolve_until_stable()
    return eng, bear


def test_the_restriction_blocks_a_blue_spell_this_turn_only():
    eng, bear = _veiled_bear()
    assert bear.temp_cant_be_target_of_spell_colors
    assert not targeting._targetable_by(bear, _blue_spell())
    assert targeting._targetable_by(bear, _red_spell())  # only blue and black are refused
    advance_to(eng, "cleanup")
    eng.advance_step()  # RULE 514.2: cleanup ends "this turn" effects
    assert not bear.temp_cant_be_target_of_spell_colors
    assert targeting._targetable_by(bear, _blue_spell())


def test_a_clone_keeps_the_live_restriction_and_one_taken_after_cleanup_has_none():
    eng, bear = _veiled_bear()
    live_twin = eng.state.clone().find_object(bear.instance_id)
    assert live_twin.temp_cant_be_target_of_spell_colors == bear.temp_cant_be_target_of_spell_colors
    assert not targeting._targetable_by(live_twin, _blue_spell())
    advance_to(eng, "cleanup")
    eng.advance_step()
    expired_twin = eng.state.clone().find_object(bear.instance_id)
    assert not expired_twin.temp_cant_be_target_of_spell_colors
    assert targeting._targetable_by(expired_twin, _blue_spell())
    assert live_twin.temp_cant_be_target_of_spell_colors  # the earlier clone is an independent copy
