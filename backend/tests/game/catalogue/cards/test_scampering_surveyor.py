"""Scampering Surveyor (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = 'Scampering Surveyor'


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first][:0] == []


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.triggered_abilities


def test_end_to_end():
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _zone_card
    engine = _game()
    player = engine.state.players[0]
    cave = _zone_card(engine, "Hidden Cave", "Land — Cave", "p1", Zone.LIBRARY)
    bad = _zone_card(engine, "Nonbasic", "Land", "p1", Zone.LIBRARY)
    surveyor = _card(engine, NAME, zone=Zone.HAND)
    for _ in range(10):
        if engine.state.current_step == "main1": break
        engine.advance_step()
    player.mana_pool.add("C", 4)
    engine.cast_spell(player, surveyor)
    engine.resolve_until_stable()
    offered = {str(o.get("instance_id")) for o in engine.state.pending_choice["options"]}
    assert str(cave.instance_id) in offered
    assert str(bad.instance_id) not in offered
    engine.resolve_pending_choice(str(cave.instance_id))
    engine.resolve_until_stable()
    assert cave in engine.state.battlefield and cave.tapped
