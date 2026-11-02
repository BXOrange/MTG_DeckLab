"""Hurkyl, Master Wizard (hand-authored)."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import two_player_game

NAME = 'Hurkyl, Master Wizard'


def _hurkyl(engine):
    obj = GameObject(CardDatabase(DB_PATH).get_card(NAME), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _stock_library(engine, specs):
    """Put ``(name, type_line)`` cards on top of p1's library; the first listed ends up on top."""
    player = engine.state.player_by_id("p1")
    made = []
    for name, type_line in reversed(specs):
        card = Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
                    is_land="Land" in type_line, is_instant="Instant" in type_line)
        obj = GameObject(card, owner_id="p1", zone=Zone.LIBRARY)
        player.add_to_zone(obj, Zone.LIBRARY)
        made.append(obj)
    return {o.name: o for o in made}


def _cast(engine, *type_words, player="p1"):
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=player, object_types=list(type_words)))


def _to_main(engine):
    """Past the draw step, so the stocked library is not drawn from and the turn's events carry the real turn number."""
    while engine.state.current_step != "main1":
        engine.advance_step()


def _to_end_step(engine):
    for _ in range(20):
        if engine.state.current_step == "end":
            return
        engine.advance_step()
    raise AssertionError("end step not reached")


def test_registered_and_fresh_each_call():
    engine, _ = two_player_game()
    obj = _hurkyl(engine)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first] == ['triggered']


def test_binds_onto_the_object():
    engine, _ = two_player_game()
    assert len(_hurkyl(engine).triggered_abilities) == 1


def test_end_to_end():
    engine, _ = two_player_game()
    _hurkyl(engine)
    _to_main(engine)
    cards = _stock_library(engine, [
        ("Top Artifact", "Artifact"), ("Top Creature", "Creature — Bear"), ("Top Instant", "Instant"),
        ("Top Land", "Land"), ("Top Enchantment", "Enchantment"), ("Deep Instant", "Instant"),
    ])
    _cast(engine, "instant")
    _cast(engine, "artifact")  # two noncreature types: artifact and instant (sorted: artifact first)
    _cast(engine, "creature")  # a creature spell contributes no type
    _to_end_step(engine)
    engine.resolve_until_stable()
    p1 = engine.state.player_by_id("p1")

    choice = engine.state.pending_choice
    assert choice["kind"] == "type_pick" and choice["card_type"] == "artifact"
    assert [o["label"] for o in choice["options"] if "instance_id" in o] == ["Top Artifact"]
    engine.rules.resolve_choice(str(cards["Top Artifact"].instance_id))

    choice = engine.state.pending_choice
    assert choice["card_type"] == "instant"
    assert [o["label"] for o in choice["options"] if "instance_id" in o] == ["Top Instant"]  # Deep Instant is 6th
    engine.rules.resolve_choice(str(cards["Top Instant"].instance_id))

    assert engine.state.pending_choice is None
    assert {o.name for o in p1.hand} >= {"Top Artifact", "Top Instant"}
    # The three unpicked revealed cards go to the bottom; the sixth card is untouched and now on top.
    assert p1.library[-1].name == "Deep Instant"
    assert {o.name for o in p1.library[:3]} == {"Top Creature", "Top Land", "Top Enchantment"}


def test_declining_every_pick_still_bottoms_the_revealed_cards():
    engine, _ = two_player_game()
    _hurkyl(engine)
    _to_main(engine)
    _stock_library(engine, [("A", "Artifact"), ("B", "Instant"), ("C", "Land"), ("D", "Land"), ("E", "Land"),
                            ("Untouched", "Land")])
    _cast(engine, "instant")
    _to_end_step(engine)
    engine.resolve_until_stable()
    engine.rules.resolve_choice("decline")
    p1 = engine.state.player_by_id("p1")
    assert engine.state.pending_choice is None
    assert not any(o.name in {"A", "B"} for o in p1.hand)
    assert p1.library[-1].name == "Untouched"


def test_no_trigger_without_a_noncreature_spell():
    engine, _ = two_player_game()
    _hurkyl(engine)
    _to_main(engine)
    _stock_library(engine, [("A", "Artifact")] * 6)
    _cast(engine, "creature")
    _to_end_step(engine)
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    assert engine.state.player_by_id("p1").hand == []
