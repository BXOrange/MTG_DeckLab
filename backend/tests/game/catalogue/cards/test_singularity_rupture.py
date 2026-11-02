"""Singularity Rupture (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Singularity Rupture'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.spell_effects


@pytest.mark.parametrize("target_count", [0, 1, 2])
def test_end_to_end(target_count):
    engine = _game()
    player = engine.state.players[0]
    bears = [_card(engine, "Grizzly Bears", player=p.id) for p in engine.state.players]
    spell = _card(engine, NAME, zone=Zone.HAND)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    before = [len(p.library) for p in engine.state.players]
    player.mana_pool.add_many({"U": 1, "B": 2, "C": 3})
    engine.cast_spell(player, spell, targets=engine.state.players[:target_count])
    engine.resolve_until_stable()
    assert all(o.zone == Zone.GRAVEYARD for o in bears)
    for i,p in enumerate(engine.state.players):
        assert len(p.library) == before[i] - (before[i] // 2 if i < target_count else 0)
