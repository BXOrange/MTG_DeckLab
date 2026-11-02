"""Lazav, Wearer of Faces (hand-authored)."""

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.linked_exile import linked_cards
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import two_player_game

NAME = 'Lazav, Wearer of Faces'


def _lazav(engine):
    card = Card(id=NAME, name=NAME, type_line="Legendary Creature — Shapeshifter Detective",
                is_creature=True, power=1, toughness=3)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _exiled_with(engine, lazav, name, type_line, power=None, toughness=None):
    """A card in exile linked to Lazav (RULE 607.2a), as his attack trigger leaves it."""
    card = Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
                power=power, toughness=toughness)
    obj = GameObject(card, owner_id="p2", zone=Zone.EXILE)
    engine.state.player_by_id("p2").add_to_zone(obj, Zone.EXILE)
    engine.state.track_exiled_with(lazav, obj, lazav.zone_incarnation)
    return obj


def test_registered_and_fresh_each_call():
    engine, _ = two_player_game()
    obj = _lazav(engine)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    engine, _ = two_player_game()
    assert len(_lazav(engine).triggered_abilities) == 2


def _clue_sacrificed(engine):
    clue = GameObject(Card(id="Clue", name="Clue", type_line="Artifact — Clue"),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    clue.controller_id = "p1"
    engine.state.add_to_battlefield(clue)
    engine.rules.put_into_graveyard(clue)
    return clue


def test_end_to_end():
    engine, _ = two_player_game()
    lazav = _lazav(engine)
    _exiled_with(engine, lazav, "Linked Dragon", "Creature — Dragon", 5, 4)
    _clue_sacrificed(engine)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    # Only one creature card is linked, so the optional copy is offered as a yes/no pick.
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects" and choice["optional"] is True
    engine.rules.resolve_choice("decline")  # "you may": declining leaves Lazav as printed
    continuous.recompute(engine.state)
    assert lazav.power == 1 and lazav.toughness == 3

    _clue_sacrificed(engine)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice(str(choice["options"][0]["id"]))
    continuous.recompute(engine.state)
    assert lazav.power == 5 and lazav.toughness == 4


def test_attack_exile_links_the_card_to_lazav():
    engine, _ = two_player_game()
    lazav = _lazav(engine)
    dragon = GameObject(Card(id="Gy Dragon", name="Gy Dragon", type_line="Creature — Dragon",
                             is_creature=True, power=5, toughness=4),
                        owner_id="p2", zone=Zone.GRAVEYARD)
    engine.state.player_by_id("p2").add_to_zone(dragon, Zone.GRAVEYARD)
    engine.state.fire_event(GameEvent(
        EventType.ATTACKS, instance_id=lazav.instance_id, player_id="p1", attacker=lazav.name,
        zone_incarnation=lazav.zone_incarnation, declared=True))
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_choice(str(dragon.instance_id))  # RULE 603.3d: the trigger's target
    engine.rules.resolve_top_of_stack()
    assert dragon.zone == Zone.EXILE
    assert linked_cards(engine.state, lazav) == [dragon]


def test_noncreature_exiled_card_is_not_a_template():
    engine, _ = two_player_game()
    lazav = _lazav(engine)
    _exiled_with(engine, lazav, "Linked Island", "Basic Land — Island")
    _clue_sacrificed(engine)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    continuous.recompute(engine.state)
    assert lazav.power == 1 and lazav.toughness == 3


def test_other_artifact_sacrifice_does_not_trigger():
    engine, _ = two_player_game()
    lazav = _lazav(engine)
    _exiled_with(engine, lazav, "Linked Dragon", "Creature — Dragon", 5, 4)
    treasure = GameObject(Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure"),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    treasure.controller_id = "p1"
    engine.state.add_to_battlefield(treasure)
    engine.rules.put_into_graveyard(treasure)
    assert engine.rules.put_triggers_on_stack() == 0
