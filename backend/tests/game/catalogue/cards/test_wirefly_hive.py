"""Wirefly Hive (hand-authored)."""

import pytest

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Wirefly Hive'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:1] == ['activated']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.activated_abilities


@pytest.mark.parametrize("win", [True, False])
def test_end_to_end(monkeypatch, win):
    from tests.support.catalogue import battlefield_object
    from mtg_analyzer.services.token_database import synthesize_token_card
    engine = _game()
    player = engine.state.players[0]
    hive = _card(engine, NAME)
    my_wirefly = engine.rules.create_token("p1", synthesize_token_card("Wirefly", power=2, toughness=2, is_artifact=True, subtypes=["Insect"], keywords=["flying"]), 1)[0]
    enemy_wirefly = battlefield_object(engine, "p2", "Wirefly", "Artifact")
    other = battlefield_object(engine, "p2", "Other Insect", "Artifact Creature — Insect", is_creature=True, power=2, toughness=2)
    monkeypatch.setattr(engine.rules, "random_int", lambda upper: 0 if win else 1)
    player.mana_pool.add("C", 3)
    engine.activate_ability(player, hive)
    engine.resolve_until_stable()
    if win:
        made = [o for o in engine.state.battlefield if o.name == "Wirefly" and o is not my_wirefly and o is not enemy_wirefly]
        assert len(made) == 1
        assert made[0].power == made[0].toughness == 2 and made[0].is_artifact
        assert "flying" in made[0].granted_keywords | {k.lower() for k in made[0].card.keywords}
    else:
        assert my_wirefly not in engine.state.battlefield
        assert enemy_wirefly.zone == Zone.GRAVEYARD
        assert not any(o.name == "Wirefly" for o in engine.state.battlefield)
    assert other.zone == hive.zone == Zone.BATTLEFIELD
    assert hive.tapped
