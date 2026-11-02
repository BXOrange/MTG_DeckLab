"""Indoctrination Attendant (hand-authored)."""

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import battlefield_object, two_player_game

NAME = 'Indoctrination Attendant'


def _attendant(engine):
    card = CardDatabase(DB_PATH).get_card(NAME)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id="p1",
        player_id="p1", zone_incarnation=obj.zone_incarnation))
    return engine.rules.put_triggers_on_stack()


def _mites(engine):
    return [o for o in engine.state.permanents() if o.card.name == "Phyrexian Mite"]


def test_registered_and_fresh_each_call():
    engine, _ = two_player_game()
    obj = _attendant(engine)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    # The printed Toxic 1 (RULE 702.164) survives registration alongside the authored ETB trigger.
    assert sorted(s.ability_kind for s in first) == ['keyword', 'triggered']
    assert combat.toxic_value(obj) == 1


def test_binds_onto_the_object():
    engine, _ = two_player_game()
    assert len(_attendant(engine).triggered_abilities) == 1


def test_end_to_end():
    engine, _ = two_player_game()
    attendant = _attendant(engine)
    land = battlefield_object(engine, "p1", "Home Land", "Basic Land — Forest")
    assert _enter(engine, attendant) == 1
    assert engine.state.pending_choice["kind"] == "trigger_target"  # RULE 603.3d
    engine.rules.resolve_choice(str(land.instance_id))
    engine.rules.resolve_top_of_stack()
    assert land.zone == Zone.HAND  # RULE 400.7: bounced to its owner's hand
    mites = _mites(engine)
    assert len(mites) == 1
    mite = mites[0]
    continuous.recompute(engine.state)
    assert (mite.power, mite.toughness) == (1, 1)
    assert combat.toxic_value(mite) == 1
    assert "cant_block" in mite.card.keywords or "cant_block" in combat._obj_keywords(mite)


def test_declining_the_return_creates_no_token():
    engine, _ = two_player_game()
    attendant = _attendant(engine)
    battlefield_object(engine, "p1", "Home Land", "Basic Land — Forest")
    _enter(engine, attendant)
    if engine.state.pending_choice is not None:
        engine.rules.resolve_choice("decline")
    engine.rules.resolve_top_of_stack()
    if engine.state.pending_choice is not None:
        engine.rules.resolve_choice("decline")
    assert _mites(engine) == []
