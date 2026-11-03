"""Three Steps Ahead (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Three Steps Ahead'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['spell_effect']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert len(obj.spell_modes) == 3


@pytest.mark.parametrize("modes", [[0], [1], [2], [0, 1, 2]])
def test_end_to_end(modes):
    engine = _game()
    player, opponent = engine.state.players
    bear = _card(engine, "Grizzly Bears")
    enemy_spell = _card(engine, "Grizzly Bears", player="p2", zone=Zone.HAND)
    engine.rules.cast_without_paying(opponent, enemy_spell)
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add_many({"U": 2, "C": 6})
    groups = ([[enemy_spell]] if 0 in modes else []) + ([[bear]] if 1 in modes else [])
    engine.cast_spell(player, spell, mode=modes, target_groups=groups)
    engine.resolve_until_stable()
    if 2 in modes:
        assert len(player.hand) == 2
        engine.resolve_pending_choice(str(player.hand[0].instance_id))
        engine.resolve_until_stable()
        assert len(player.hand) == 1
    assert enemy_spell.zone == (Zone.GRAVEYARD if 0 in modes else Zone.BATTLEFIELD)
    assert len([o for o in engine.state.battlefield if o.is_token]) == int(1 in modes)
    assert spell.zone == Zone.GRAVEYARD


def test_spree_prices_each_selected_mode():
    engine = _game()
    player = engine.state.players[0]
    spell = _card(engine, NAME, zone=Zone.HAND)
    player.mana_pool.add("U", 1)
    assert not engine.can_cast(player, spell, mode=[2])
    player.mana_pool.add("C", 2)
    assert engine.can_cast(player, spell, mode=[2])
    assert not engine.can_cast(player, spell, mode=[1, 2])
