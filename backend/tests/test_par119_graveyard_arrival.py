"""PAR-119 (c) — "whenever `<a card>` is put into `<whose>` graveyard [from `<origin>`]".

RULE 603.6c: a "from anywhere" trigger is never a leaves-the-battlefield ability, and the
engine writes to graveyards from many places, so `GameState` detects each arrival when a
simultaneity scope closes and fires `EventType.PUT_INTO_GRAVEYARD` (batched, RULE 603.2c).
RULE 113.6k: "when ~ is put into a graveyard" functions from the graveyard.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.services.card_database import CardDatabase


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _card(name, type_line="Instant", **kw):
    return Card(id=name, name=name, type_line=type_line, **kw)


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _listener(state, oracle, owner="p1"):
    card = _card("Listener", "Enchantment", oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, owner)


def _library(engine, pid, cards):
    player = engine.state.player_by_id(pid)
    for card in cards:
        obj = GameObject(card, owner_id=pid, zone=Zone.LIBRARY)
        bind_from_catalogue(obj)
        player.library.append(obj)
    engine.state.resync_graveyard_watch()  # a real game had these cards from the start
    return player


def _settle(engine):
    """An SBA sweep closes a scope, as it does before every priority (RULE 704.3)."""
    engine.state.announce_graveyard_arrivals()
    engine.resolve_until_stable()


LANDS = "Whenever a land card is put into your graveyard from anywhere, you gain 1 life."


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond, event, condition, trigger", [
    ("a land card is put into your graveyard from anywhere", "PUT_INTO_GRAVEYARD",
     {"subject": "group", "controller": "you", "other": False,
      "filter": {"card_type": "land"}, "nontoken": True}, {}),
    ("a creature card is put into an opponent's graveyard from anywhere", "PUT_INTO_GRAVEYARD",
     {"subject": "group", "controller": "not_you", "other": False,
      "filter": {"card_type": "creature"}, "nontoken": True}, {}),
    ("~ is put into a graveyard from anywhere", "PUT_INTO_GRAVEYARD", {"subject": "self"}, {}),
    ("this card is put into your graveyard from your library", "PUT_INTO_GRAVEYARD",
     {"subject": "self"}, {"filter": {"from_zone": "library"}}),
    ("a creature card is put into a graveyard from anywhere other than the battlefield",
     "PUT_INTO_GRAVEYARD",
     {"subject": "group", "controller": "any", "other": False,
      "filter": {"card_type": "creature"}, "nontoken": True}, {"from_zone_not": "battlefield"}),
    # A permanent only exists on the battlefield, so that is the unstated origin.
    ("a permanent is put into an opponent's graveyard", "PUT_INTO_GRAVEYARD",
     {"subject": "group", "controller": "not_you", "other": False},
     {"filter": {"from_zone": "battlefield"}}),
    ("1 or more land cards are put into your graveyard from anywhere", "EVENT_BATCH",
     {"subject": "group", "controller": "you", "other": False,
      "filter": {"card_type": "land"}, "nontoken": True},
     {"batch": {"of": "PUT_INTO_GRAVEYARD", "min": 1}}),
])
def test_graveyard_arrival_head(cond, event, condition, trigger):
    head = parse_object_trigger_head(cond)
    assert head is not None
    assert (head.event, head.condition, head.trigger) == (event, condition, trigger)


@pytest.mark.parametrize("cond", [
    # A leaves-the-battlefield ability looks back in time (RULE 603.10a) — not this head.
    "a creature is put into a graveyard from the battlefield",
    # A card only ever goes to its owner's graveyard.
    "~ is put into an opponent's graveyard from anywhere",
    # Two scopes on one card are not modelled.
    "a creature card you own is put into your graveyard from anywhere",
])
def test_graveyard_arrival_head_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_a_milled_land_is_an_arrival_from_the_library():
    engine = _engine()
    _listener(engine.state, LANDS)
    events = []
    engine.state.subscribe(lambda e: events.append(e) if e.type == EventType.PUT_INTO_GRAVEYARD else None)
    you = _library(engine, "p1", [_card("Forest", "Basic Land — Forest", is_land=True)])
    engine.rules.mill(you, 1)
    _settle(engine)
    assert you.life == 21
    assert [(e.get("object"), e.get("from_zone")) for e in events] == [("Forest", "library")]


def test_a_discarded_land_counts_and_an_instant_does_not():
    engine = _engine()
    _listener(engine.state, LANDS)
    you = engine.state.player_by_id("p1")
    for card in (_card("Shock"), _card("Swamp", "Basic Land — Swamp", is_land=True)):
        you.hand.append(GameObject(card, owner_id="p1", zone=Zone.HAND))
    engine.state.resync_graveyard_watch()
    engine.rules.discard(you, 2)
    _settle(engine)
    assert you.life == 21


def test_an_opponents_graveyard_is_not_yours():
    engine = _engine()
    _listener(engine.state, LANDS)
    them = _library(engine, "p2", [_card("Island", "Basic Land — Island", is_land=True)])
    engine.rules.mill(them, 1)
    _settle(engine)
    assert engine.state.player_by_id("p1").life == 20


def test_a_card_already_in_the_graveyard_is_not_announced_again():
    engine = _engine()
    _listener(engine.state, LANDS)
    you = _library(engine, "p1", [_card("Forest", "Basic Land — Forest", is_land=True)])
    engine.rules.mill(you, 1)
    _settle(engine)
    _settle(engine)
    assert you.life == 21


def test_a_batch_counts_once_for_a_mass_mill():
    engine = _engine()
    _listener(engine.state,
              "Whenever one or more land cards are put into your graveyard from anywhere, "
              "you gain 1 life.")
    you = _library(engine, "p1", [_card(f"Forest{i}", "Basic Land — Forest", is_land=True)
                                  for i in range(3)])
    with engine.state.simultaneous():
        engine.rules.mill(you, 3)
    engine.resolve_until_stable()
    assert you.life == 21


def test_other_than_the_battlefield_excludes_a_death():
    engine = _engine()
    _listener(engine.state,
              "Whenever a creature card is put into a graveyard from anywhere other than the "
              "battlefield, you gain 1 life.")
    bear = _bf(engine.state, _card("Bear", "Creature — Bear", is_creature=True, power=2, toughness=2))
    engine.state.resync_graveyard_watch()
    engine.rules.destroy(bear)
    _settle(engine)
    you = engine.state.player_by_id("p1")
    assert you.life == 20
    _library(engine, "p1", [_card("Wolf", "Creature — Wolf", is_creature=True, power=2, toughness=2)])
    engine.rules.mill(you, 1)
    _settle(engine)
    assert you.life == 21


PATRON = "Whenever a permanent is put into an opponent's graveyard, that player loses 1 life."


def test_a_dying_token_is_a_permanent_put_into_a_graveyard():
    engine = _engine()
    _listener(engine.state, PATRON)
    token = _bf(engine.state, _card("Tok", "Token Creature — Bear", is_creature=True,
                                    power=2, toughness=2), owner="p2")
    token.is_token = True
    engine.state.resync_graveyard_watch()
    token.damage_marked = 5
    engine.rules.check_state_based_actions()
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 19


def test_a_milled_card_is_not_a_permanent():
    engine = _engine()
    _listener(engine.state, PATRON)
    them = _library(engine, "p2", [_card("Island", "Basic Land — Island", is_land=True)])
    engine.rules.mill(them, 1)
    _settle(engine)
    assert them.life == 20


def test_a_stolen_creature_is_its_owners_in_the_graveyard():
    """RULE 108.4a: "that player" is the owner, not the player who had stolen it."""
    engine = _engine()
    _listener(engine.state, PATRON)
    stolen = _bf(engine.state, _card("Bear", "Creature — Bear", is_creature=True,
                                     power=2, toughness=2), owner="p2")
    stolen.controller_id = "p1"  # Alice stole Bob's Bear
    engine.state.resync_graveyard_watch()
    engine.rules.destroy(stolen)
    _settle(engine)
    assert engine.state.player_by_id("p2").life == 19
    assert engine.state.player_by_id("p2").graveyard[0].controller_id == "p2"


def test_a_self_trigger_functions_from_the_graveyard():
    engine = _engine()
    card = _card("Avatar", "Creature — Avatar", is_creature=True, power=1, toughness=1,
                 oracle_text="When this card is put into a graveyard from anywhere, "
                             "shuffle it into its owner's library.")
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    you = _library(engine, "p1", [card])
    engine.rules.mill(you, 1)
    _settle(engine)
    assert [o.name for o in you.graveyard] == []
    assert [o.name for o in you.library] == ["Avatar"]


def test_a_direct_board_edit_can_be_rebaselined_without_firing():
    engine = _engine()
    _listener(engine.state, LANDS)
    engine.state.announce_graveyard_arrivals()
    you = engine.state.player_by_id("p1")
    you.graveyard.append(GameObject(_card("Forest", "Basic Land — Forest", is_land=True),
                                    owner_id="p1", zone=Zone.GRAVEYARD))
    engine.state.resync_graveyard_watch()
    _settle(engine)
    assert you.life == 20


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "The Gitrog Monster", "Profane Memento", "Serra Avatar", "Worldspine Wurm", "Compost",
    "Skola Grovedancer", "Crawling Infestation", "Energy Field",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.full_cache
def test_profane_memento_gains_life_off_an_opponents_creature_card():
    engine = _engine()
    _bf(engine.state, CardDatabase(DB_PATH).get_card("Profane Memento"))
    them = _library(engine, "p2", [_card("Wolf", "Creature — Wolf", is_creature=True,
                                         power=2, toughness=2)])
    engine.rules.mill(them, 1)
    _settle(engine)
    assert engine.state.player_by_id("p1").life == 21
