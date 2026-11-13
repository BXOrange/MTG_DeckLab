"""ENG-54: `RETURNED_TO_HAND` / `PUT_INTO_LIBRARY` zone-arrival events and their trigger heads (RULE 603.6c).

Detected as a zone diff when a `simultaneous` scope closes (like `PUT_INTO_GRAVEYARD`): one event per real
zone change, batched per action (RULE 603.2c); draws, mills, shuffles and setup moves are not arrivals.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

RETURNED, PUT = EventType.RETURNED_TO_HAND, EventType.PUT_INTO_LIBRARY


def _engine(hand=0):
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=hand)


def _card(name, type_line="Instant", **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _creature(name="Bear"):
    return _card(name, "Creature — Bear", is_creature=True, power=2, toughness=2)


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _listener(state, oracle, owner="p1", type_line="Creature — Human", name="Listener"):
    card = _card(name, type_line, oracle_text=oracle, is_creature="Creature" in type_line, power=1, toughness=1)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, owner)


def _library(engine, pid, cards):
    player = engine.state.player_by_id(pid)
    for card in cards:
        obj = GameObject(card, owner_id=pid, zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        player.library.append(obj)
    engine.state.resync_graveyard_watch()
    return player


def _record(engine, *types):
    events = []
    engine.state.subscribe(lambda e: events.append(e) if e.type in types else None)
    return events


def _settle(engine):
    engine.state.announce_graveyard_arrivals()
    engine.resolve_until_stable()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
def test_a_bounced_permanent_is_returned_to_hand_once():
    engine = _engine()
    events = _record(engine, RETURNED, PUT)
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(bear)
    _settle(engine)
    _settle(engine)
    assert [(e.type, e.get("from_zone"), e.get("from_battlefield"), e.get("owner_id"), e.get("controller_before"),
             e.get("object")) for e in events] == [(RETURNED, "battlefield", True, "p1", "p1", "Bear")]
    assert "creature" in events[0].get("object_types")


def test_a_stolen_permanent_returns_to_its_owners_hand():
    engine = _engine()
    events = _record(engine, RETURNED)
    bear = _bf(engine.state, _creature(), owner="p2")
    bear.controller_id = "p1"
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(bear)
    _settle(engine)
    assert [(e.get("owner_id"), e.get("controller_id"), e.get("controller_before")) for e in events] == [
        ("p2", "p2", "p1")]


def test_a_card_returned_from_the_graveyard_is_returned_to_hand():
    engine = _engine()
    events = _record(engine, RETURNED)
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    engine.rules.destroy(bear)
    _settle(engine)
    assert events == []
    engine.rules.return_from_graveyard(bear, destination="hand")
    _settle(engine)
    assert [(e.get("from_zone"), e.get("from_battlefield")) for e in events] == [("graveyard", False)]


def test_a_mass_bounce_is_one_batch():
    engine = _engine()
    batches = _record(engine, EventType.EVENT_BATCH)
    bears = [_bf(engine.state, _creature(f"Bear{i}")) for i in range(3)]
    engine.state.resync_graveyard_watch()
    with engine.state.simultaneous():
        for bear in bears:
            engine.rules.return_to_hand(bear)
    returned = [b for b in batches if b.get("batch_of") == RETURNED]
    assert len(returned) == 1 and len(returned[0].get("members")) == 3


@pytest.mark.parametrize("position", ["top", "bottom"])
def test_a_tucked_card_is_put_into_a_library(position):
    engine = _engine()
    events = _record(engine, PUT, RETURNED)
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_library(bear, position=position)
    _settle(engine)
    assert [(e.type, e.get("from_zone"), e.get("owner_id")) for e in events] == [(PUT, "battlefield", "p1")]


def test_shuffling_a_card_into_a_library_counts_but_the_shuffle_itself_does_not():
    engine = _engine()
    events = _record(engine, PUT)
    bear = _bf(engine.state, _creature())
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(3)])
    engine.rules.shuffle_into_library(bear)
    _settle(engine)
    assert [e.get("instance_id") for e in events] == [bear.instance_id]
    events.clear()
    engine.rules.shuffle_library(you)
    _settle(engine)
    assert events == []


def test_milling_and_drawing_are_no_arrivals():
    engine = _engine()
    events = _record(engine, PUT, RETURNED)
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(4)])
    engine.rules.mill(you, 1)
    _settle(engine)
    you.draw(1)
    _settle(engine)
    engine.rules.draw_cards(you, 1) if hasattr(engine.rules, "draw_cards") else None
    _settle(engine)
    assert events == []


def test_setup_moves_do_not_fire():
    engine = GameEngine.new_game(
        [("p1", "Alice", [_card(f"C{i}") for i in range(10)]), ("p2", "Bob", [])], starting_life=20, starting_hand=7)
    events = _record(engine, PUT, RETURNED)
    _settle(engine)
    assert events == []


def test_a_mulligan_is_setup_not_a_library_arrival():
    from mtg_analyzer.services.game_session import GameSession
    session = GameSession.__new__(GameSession)
    session.engine = _engine()
    session._mulligan_counts = {}
    session.mulligan_style = "london"
    session._starting_hand = 3
    you = _library(session.engine, "p1", [_card(f"C{i}") for i in range(10)])
    you.draw(3)
    session.engine.state.resync_graveyard_watch()
    events = _record(session.engine, PUT, RETURNED)
    session._mulligan(you)
    _settle(session.engine)
    assert events == []


def test_hidden_library_arrival_carries_no_card_name_and_the_feed_ignores_it():
    from mtg_analyzer.services.table_feed import ANNOUNCED_EVENTS
    engine = _engine()
    events = _record(engine, PUT)
    you = engine.state.player_by_id("p1")
    secret = GameObject(_card("Secret Plan"), owner_id="p1", zone=Zone.HAND)
    you.add_to_zone(secret, Zone.HAND)
    engine.state.resync_graveyard_watch()
    you.remove_from_zone(secret, Zone.HAND)
    you.add_to_zone(secret, Zone.LIBRARY)
    _settle(engine)
    assert len(events) == 1 and events[0].get("from_zone") == "hand"
    assert events[0].get("object") is None
    assert RETURNED not in ANNOUNCED_EVENTS and PUT not in ANNOUNCED_EVENTS


# ---------------------------------------------------------------------------
# Heads
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cond,event", [
    ("a permanent is returned to your hand", RETURNED),
    ("~ or another creature is returned to your hand from the battlefield", RETURNED),
    ("1 or more noncreature permanents are returned to hand", EventType.EVENT_BATCH),
    ("1 or more cards are put into a library from anywhere", EventType.EVENT_BATCH),
    ("a card is put into your library from anywhere", PUT),
])
def test_arrival_heads_parse(cond, event):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == event


@pytest.mark.parametrize("cond", [
    "a permanent is returned to hand from anywhere",
    "a creature is put into a library from the battlefield",
    "1 or more cards are returned to your hand sideways",
])
def test_arrival_heads_fail_closed(cond):
    assert parse_object_trigger_head(cond) is None


# ---------------------------------------------------------------------------
# The five cards' triggers, executed
# ---------------------------------------------------------------------------
AETHERMAGE = "Whenever a permanent is returned to your hand, you may pay {1}. If you do, draw a card."
STORMFRONT = "Whenever ~ or another creature is returned to your hand from the battlefield, create a 1/1 white Soldier creature token."
TAMESHI = "Whenever 1 or more noncreature permanents are returned to hand, draw a card. This ability triggers only once each turn."
SEEKER = "Whenever 1 or more cards are put into a library from anywhere, put a +1/+1 counter on ~."
WAN = "Whenever 1 or more cards are put into a library from anywhere, create 2 1/1 colorless Spirit creature tokens."


def _soldiers(engine):
    return [o for o in engine.state.battlefield if o.name == "Soldier"]


def test_stormfront_riders_triggers_for_itself_and_each_other_creature():
    engine = _engine()
    riders = _listener(engine.state, STORMFRONT, name="Riders")
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    with engine.state.simultaneous():
        # The engine moves a mass bounce one permanent at a time, so (as for every leaves-the-battlefield
        # ability) a source moved first no longer sees the others; the source goes last here.
        engine.rules.return_to_hand(bear)
        engine.rules.return_to_hand(riders)
    _settle(engine)
    assert len(_soldiers(engine)) == 2  # RULE 603.2: one trigger per creature (its ruling), not one per batch


def test_stormfront_riders_ignores_an_opponents_bounce_and_a_graveyard_return():
    engine = _engine()
    _listener(engine.state, STORMFRONT, name="Riders")
    theirs = _bf(engine.state, _creature("Theirs"), owner="p2")
    mine = _bf(engine.state, _creature("Mine"))
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(theirs)
    _settle(engine)
    assert _soldiers(engine) == []
    engine.rules.destroy(mine)
    _settle(engine)
    engine.rules.return_from_graveyard(mine, destination="hand")
    _settle(engine)
    assert _soldiers(engine) == []


def test_tameshi_draws_once_per_batch_and_once_each_turn_and_only_for_noncreature_permanents():
    engine = _engine()
    _listener(engine.state, TAMESHI, name="Tameshi")
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(5)])
    rock = _bf(engine.state, _card("Rock", "Artifact"))
    rock2 = _bf(engine.state, _card("Rock2", "Artifact"), owner="p2")
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(bear)
    _settle(engine)
    assert len(you.hand) == 1 and len(you.library) == 5  # only the bounced creature itself; no draw
    with engine.state.simultaneous():
        engine.rules.return_to_hand(rock)
        engine.rules.return_to_hand(rock2)
    _settle(engine)
    assert len(you.library) == 4  # one draw for the batch, an opponent's permanent included
    _bf(engine.state, _card("Rock3", "Artifact"))
    rock3 = next(o for o in engine.state.battlefield if o.name == "Rock3")
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(rock3)
    _settle(engine)
    assert len(you.library) == 4  # once each turn


def test_tameshi_ignores_a_noncreature_card_returned_from_the_graveyard():
    engine = _engine()
    _listener(engine.state, TAMESHI, name="Tameshi")
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(3)])
    rock = _bf(engine.state, _card("Rock", "Artifact"))
    engine.state.resync_graveyard_watch()
    engine.rules.destroy(rock)
    _settle(engine)
    engine.rules.return_from_graveyard(rock, destination="hand")
    _settle(engine)
    assert len(you.library) == 3


def test_azorius_aethermage_triggers_only_for_permanents_returned_to_your_hand():
    engine = _engine()
    _listener(engine.state, AETHERMAGE, name="Aethermage")
    events = _record(engine, EventType.TRIGGERED_ABILITY) if hasattr(EventType, "TRIGGERED_ABILITY") else []
    theirs = _bf(engine.state, _creature("Theirs"), owner="p2")
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(theirs)
    engine.state.announce_graveyard_arrivals()
    assert not engine.rules.pending_triggers
    mine = _bf(engine.state, _creature("Mine"))
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(mine)
    engine.state.announce_graveyard_arrivals()
    assert len(engine.rules.pending_triggers) == 1
    del events


def test_dutiful_knowledge_seeker_grows_once_for_a_batch_and_not_for_a_mill():
    engine = _engine()
    seeker = _listener(engine.state, SEEKER, name="Seeker")
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(3)])
    engine.rules.mill(you, 1)
    _settle(engine)
    assert seeker.counters.get("+1/+1", 0) == 0
    bears = [_bf(engine.state, _creature(f"Bear{i}"), owner=o) for i, o in enumerate(("p1", "p2"))]
    engine.state.resync_graveyard_watch()
    with engine.state.simultaneous():
        for bear in bears:
            engine.rules.return_to_library(bear, position="bottom")
    _settle(engine)
    assert seeker.counters.get("+1/+1", 0) == 1


def test_wan_shi_tong_makes_two_spirits_when_a_card_is_shuffled_in_but_not_on_a_reshuffle():
    engine = _engine()
    _listener(engine.state, WAN, name="Wan Shi Tong")
    you = _library(engine, "p1", [_card(f"C{i}") for i in range(3)])
    engine.rules.shuffle_library(you)
    _settle(engine)
    assert len([o for o in engine.state.battlefield if o.name == "Spirit"]) == 0
    bear = _bf(engine.state, _creature())
    engine.state.resync_graveyard_watch()
    engine.rules.shuffle_into_library(bear)
    _settle(engine)
    assert len([o for o in engine.state.battlefield if o.name == "Spirit"]) == 2


def test_azorius_aethermage_sees_itself_returned_to_hand():
    engine = _engine()
    mage = _listener(engine.state, AETHERMAGE, name="Aethermage")
    engine.state.resync_graveyard_watch()
    engine.rules.return_to_hand(mage)
    engine.state.announce_graveyard_arrivals()
    assert len(engine.rules.pending_triggers) == 1  # RULE 603.10a: it looks back at its own departure
