"""MEC-70 — RULE 702.55 Haunt links and exile-zone death triggers."""

from mtg_analyzer.game.effects.core import HauntEffect, HauntLinkedDeathEffect, TriggeredAbility
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _creature(name, owner="p1"):
    obj = GameObject(Card(id=name, name=name, type_line="Creature — Spirit", is_creature=True,
                          power=2, toughness=2), owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    return obj


def test_haunt_dies_link_fires_the_exiled_cards_linked_death_ability():
    engine = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    engine.begin_turn()
    state = engine.state
    state.player_by_id("p1").library.append(
        GameObject(Card(id="draw", name="Draw", type_line="Instant", is_instant=True),
                   owner_id="p1", zone=Zone.LIBRARY)
    )
    haunter = _creature("Haunter")
    haunted = _creature("Haunted", owner="p2")
    state.add_to_battlefield(haunter)
    state.add_to_battlefield(haunted)
    haunter.triggered_abilities = [
        TriggeredAbility(EventType.DIES, [HauntEffect(source=haunter)], source=haunter,
                         controller_id="p1", description="Haunt"),
        TriggeredAbility(
            EventType.DIES,
            [HauntLinkedDeathEffect([{"type": "draw", "params": {"count": 1}}], source=haunter)],
            source=haunter, controller_id="p1", description="haunted creature dies",
        ),
    ]

    engine.rules.put_into_graveyard(haunter)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(haunted.instance_id)
    engine.resolve_until_stable()
    assert haunter.zone == Zone.EXILE
    assert haunter.haunting_instance_id == haunted.instance_id

    engine.rules.put_into_graveyard(haunted)
    engine.resolve_until_stable()
    assert len(state.player_by_id("p1").hand) == 1


def test_activated_haunt_variant_exiles_source_and_links_target():
    engine = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    state = engine.state
    source = _creature("Activated Haunter")
    target = _creature("Victim", owner="p2")
    state.add_to_battlefield(source)
    state.add_to_battlefield(target)

    HauntEffect(source=source).apply(engine.rules.context, [target])
    assert source.zone == Zone.EXILE
    assert source.haunting_instance_id == target.instance_id


def test_haunt_keyword_binds_its_inherent_dies_trigger():
    engine = GameEngine.new_game(
        [("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0
    )
    state = engine.state
    source = _creature("Keyword Haunter")
    source.card.keywords = ["Haunt"]
    target = _creature("Target", owner="p2")
    state.add_to_battlefield(source)
    state.add_to_battlefield(target)
    bind_from_catalogue(source)

    engine.rules.put_into_graveyard(source)
    engine.resolve_until_stable()
    assert state.pending_choice and state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(target.instance_id)
    engine.resolve_until_stable()
    assert source.zone == Zone.EXILE and source.haunting_instance_id == target.instance_id
