"""Nahiri's Resolve (hand-authored)."""

from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.game.game_object import Zone
from tests.game.catalogue.cards.test_riveteer_rampage_deck import _card, _game

NAME = "Nahiri's Resolve"


def test_registered_and_fresh_each_call():
    obj = _card(_game(), NAME, zone=Zone.HAND)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # Prefix compare: the engine auto-adds keyword abilities (Equip, Forecast, ...) after the hand-written ones.
    assert [s.ability_kind for s in first] == ['static', 'triggered']


def test_binds_onto_the_object():
    obj = _card(_game(), NAME, zone=Zone.BATTLEFIELD)
    assert obj.static_effects


def test_end_to_end():
    from tests.support.catalogue import battlefield_object
    from tests.game.catalogue.cards.test_riveteer_rampage_deck import _end_step
    engine = _game()
    resolve = _card(engine, NAME)
    creature = battlefield_object(engine, "p1", "Bear", "Creature", is_creature=True, power=2, toughness=2)
    artifact = battlefield_object(engine, "p1", "Relic", "Artifact")
    token = battlefield_object(engine, "p1", "Token", "Creature", is_creature=True, power=2, toughness=2)
    token.is_token = True
    engine.recompute_continuous_effects()
    assert creature.power == 3 and "haste" in creature.granted_keywords
    _end_step(engine)
    options = {o["id"] for o in engine.state.pending_choice["options"]}
    assert str(creature.instance_id) in options and str(artifact.instance_id) in options
    assert str(token.instance_id) not in options
    engine.resolve_pending_choice(str(creature.instance_id))
    engine.resolve_pending_choice(str(artifact.instance_id))
    engine.resolve_until_stable()
    assert creature.zone == artifact.zone == Zone.EXILE
    assert token.zone == Zone.BATTLEFIELD
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == "p2":
            break
    assert creature.zone == artifact.zone == Zone.EXILE
    for _ in range(30):
        engine.advance_step()
        engine.resolve_until_stable()
        if engine.state.current_step == "upkeep" and engine.state.active_player.id == "p1":
            break
    assert creature.zone == artifact.zone == Zone.BATTLEFIELD
