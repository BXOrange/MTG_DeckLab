"""Blu, Mansion Prince (hand-authored)."""

from tests.support.card_cache import get_cached_card

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.game.effects import room_tokens
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import two_player_game

NAME = 'Blu, Mansion Prince'
ROOM = 'Bottomless Pool // Locker Room'


def _blu(engine):
    obj = GameObject(get_cached_card(NAME), owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _sacrifice_clue(engine):
    clue = GameObject(Card(id="Clue", name="Clue", type_line="Artifact — Clue"),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    clue.controller_id = "p1"
    engine.state.add_to_battlefield(clue)
    engine.rules.put_into_graveyard(clue)


def test_registered_and_fresh_each_call():
    engine, _ = two_player_game()
    obj = _blu(engine)
    first, second = specs_for(obj.card), specs_for(obj.card)
    assert first and first is not second and first[0] is not second[0]
    assert [s.ability_kind for s in first] == ['triggered', 'triggered']


def test_binds_onto_the_object():
    engine, _ = two_player_game()
    # "enters" and "attacks" are one printed trigger bound once per event, plus the Clue-sacrifice trigger.
    assert len(_blu(engine).triggered_abilities) == 3


def test_room_pool_is_every_paper_room():
    pool = room_tokens.room_pool()
    assert ROOM in pool
    assert 'Crude Abattoir // Unsavory Kitchen' not in pool  # Alchemy: permanent non-goal
    assert len(pool) >= 25


def test_end_to_end(monkeypatch):
    monkeypatch.setattr(room_tokens, "_ROOM_POOL", [ROOM])  # force the "random" pick
    engine, _ = two_player_game()
    _blu(engine)
    unlocked = []
    engine.state.subscribe(lambda event: unlocked.append(event) if event.type == EventType.DOOR_UNLOCKED else None)
    _sacrifice_clue(engine)
    assert engine.rules.put_triggers_on_stack() == 1
    engine.rules.resolve_top_of_stack()
    choice = engine.state.pending_choice
    assert choice["kind"] == "room_half_choice" and choice["player_id"] == "p1"
    assert [o["label"] for o in choice["options"]] == ["Bottomless Pool", "Locker Room"]
    engine.rules.resolve_choice("right")
    tokens = [o for o in engine.state.permanents() if o.is_token and o.name == "Locker Room"]
    assert len(tokens) == 1 and tokens[0].controller_id == "p1"
    assert "Room" in tokens[0].card.type_line
    assert [e.get("door_name") for e in unlocked] == ["Locker Room"]  # RULE 709.5h: the unlock is announced


def test_left_half_copy(monkeypatch):
    monkeypatch.setattr(room_tokens, "_ROOM_POOL", [ROOM])
    engine, _ = two_player_game()
    _blu(engine)
    _sacrifice_clue(engine)
    engine.rules.put_triggers_on_stack()
    engine.rules.resolve_top_of_stack()
    engine.rules.resolve_choice("left")
    assert [o.name for o in engine.state.permanents() if o.is_token and "Room" in o.card.type_line] == ["Bottomless Pool"]
    # "then unlock it": Bottomless Pool's "When you unlock this door" ability sees the token's own unlock (RULE 709.5h).
    assert engine.rules.put_triggers_on_stack() == 1


def test_no_trigger_for_a_non_clue_sacrifice(monkeypatch):
    monkeypatch.setattr(room_tokens, "_ROOM_POOL", [ROOM])
    engine, _ = two_player_game()
    _blu(engine)
    treasure = GameObject(Card(id="Treasure", name="Treasure", type_line="Artifact — Treasure"),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    treasure.controller_id = "p1"
    engine.state.add_to_battlefield(treasure)
    engine.rules.put_into_graveyard(treasure)
    assert engine.rules.put_triggers_on_stack() == 0
