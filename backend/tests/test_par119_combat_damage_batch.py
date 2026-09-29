"""PAR-119 (a) — combat-damage batches: "whenever `<n>` or more `<creatures>` deal combat
damage to a player".

RULE 510.2 / 603.2c: a combat damage step's damage is dealt simultaneously, so every hit
one controller's creatures land on one player is one event —
`EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER`. The head's subject is the ordinary
per-creature condition, checked against each contributor; a batch adds a count.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.characteristic_phrase import parse_object_phrase
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.services.card_database import CardDatabase

EVENT = "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"


def _engine():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    for pid in ("p1", "p2"):
        player = engine.state.player_by_id(pid)
        for i in range(10):
            player.library.append(GameObject(Card(id=f"{pid}L{i}", name=f"L{i}", type_line="Instant"),
                                             owner_id=pid, zone=Zone.LIBRARY))
    return engine


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(state, name, subtype="Bear", owner="p1", power=2):
    return _bf(state, Card(id=name, name=name, type_line=f"Creature — {subtype}", is_creature=True,
                           power=power, toughness=2), owner)


def _listener(state, oracle, owner="p1"):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, owner)


def _hit(engine, target_id, *sources):
    """One combat damage step: each source deals its power to ``target_id``."""
    target = engine.state.player_by_id(target_id)
    engine._apply_combat_damage([(target, s.power, s) for s in sources])
    engine.resolve_until_stable()


def _hand(engine, pid="p1"):
    return len(engine.state.player_by_id(pid).hand)


FAERIES = "Whenever one or more Faeries you control deal combat damage to a player, draw a card."


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond, condition, minimum", [
    ("1 or more faeries you control deal combat damage to a player",
     {"subject": "group", "controller": "you", "other": False, "filter": {"subtype": "faerie"}}, 1),
    ("1 or more creatures you control with trample deal combat damage to a player",
     {"subject": "group", "controller": "you", "other": False,
      "filter": {"card_type": "creature", "keyword": "trample"}}, 1),
    ("2 or more creatures you control deal combat damage to an opponent",
     {"subject": "group", "controller": "you", "other": False,
      "filter": {"card_type": "creature"}, "recipient_is_opponent": True}, 2),
    ("1 or more creatures an opponent controls deal combat damage to you",
     {"subject": "group", "controller": "not_you", "other": False,
      "filter": {"card_type": "creature"}, "recipient_is_you": True}, 1),
    ("1 or more dragons you control deal combat damage to 1 or more players",
     {"subject": "group", "controller": "you", "other": False, "filter": {"subtype": "dragon"}}, 1),
])
def test_combat_damage_batch_head(cond, condition, minimum):
    head = parse_object_trigger_head(cond)
    assert head is not None
    assert head.event == EVENT
    assert head.condition == condition
    assert head.trigger == {"contributors": {"min": minimum}}


@pytest.mark.parametrize("cond", [
    # The aggregate names only player recipients.
    "1 or more creatures you control deal combat damage to a creature",
    "1 or more dragons you control deal combat damage to a player or battle",
    # Noncombat damage is not a combat-damage batch.
    "1 or more creatures you control deal damage to a player",
])
def test_combat_damage_batch_head_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


def test_combat_damage_batch_head_across_all_opponents_is_one_trigger():
    # MEC-104: once per step across every opponent hit (`binding.core._contributor_condition`).
    head = parse_object_trigger_head(
        "1 or more zombies you control deal combat damage to 1 or more of your opponents"
    )
    assert head is not None and head.event == "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER"
    assert head.trigger["opponents_batch"] is True
    assert "opponents_batch" not in head.condition


@pytest.mark.parametrize("phrase, expected", [
    ("ninja or rogue creatures you control",
     ({"subtype_any": ["ninja", "rogue"], "card_type": "creature"}, "you")),
    ("ninja or rogue creature", ({"subtype_any": ["ninja", "rogue"], "card_type": "creature"}, None)),
    # Only subtypes share the trailing noun — a colour or type before it is ambiguous.
    ("red or blue creatures", None),
    ("artifact or rogue creatures", None),
])
def test_a_trailing_type_noun_is_shared_by_the_subtypes_before_it(phrase, expected):
    assert parse_object_phrase(phrase, plural=True) == expected


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_two_matching_hitters_trigger_once():
    engine = _engine()
    _listener(engine.state, FAERIES)
    a = _creature(engine.state, "Sprite", "Faerie")
    b = _creature(engine.state, "Pixie", "Faerie")
    _hit(engine, "p2", a, b)
    assert _hand(engine) == 1


def test_non_matching_hitters_do_not_trigger():
    engine = _engine()
    _listener(engine.state, FAERIES)
    _hit(engine, "p2", _creature(engine.state, "Bear"))
    assert _hand(engine) == 0


def test_one_matching_hitter_among_others_is_enough():
    engine = _engine()
    _listener(engine.state, FAERIES)
    _hit(engine, "p2", _creature(engine.state, "Bear"), _creature(engine.state, "Sprite", "Faerie"))
    assert _hand(engine) == 1


def test_an_opponents_faeries_do_not_count():
    engine = _engine()
    _listener(engine.state, FAERIES)
    _hit(engine, "p1", _creature(engine.state, "Sprite", "Faerie", owner="p2"))
    assert _hand(engine) == 0


def test_the_threshold_counts_matching_contributors():
    engine = _engine()
    _listener(engine.state,
              "Whenever two or more creatures you control deal combat damage to a player, draw a card.")
    _hit(engine, "p2", _creature(engine.state, "One"))
    assert _hand(engine) == 0
    _hit(engine, "p2", _creature(engine.state, "Two"), _creature(engine.state, "Three"))
    assert _hand(engine) == 1


def test_being_dealt_damage_by_an_opponents_creatures():
    engine = _engine()
    _listener(engine.state,
              "Whenever one or more creatures an opponent controls deal combat damage to you, "
              "draw a card.")
    _hit(engine, "p1", _creature(engine.state, "Raider", owner="p2"))
    assert _hand(engine) == 1
    _hit(engine, "p2", _creature(engine.state, "Mine"))
    assert _hand(engine) == 1


def test_the_captured_event_names_only_the_matching_contributors():
    engine = _engine()
    listener = _listener(engine.state, FAERIES)
    fae = _creature(engine.state, "Sprite", "Faerie", power=3)
    bear = _creature(engine.state, "Bear")
    ability = next(t for t in listener.triggered_abilities if t.trigger_event == EVENT)
    event = GameEvent(EventType.CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER, player_id="p1",
                      target_id="p2", is_player=True,
                      contributor_ids=[bear.instance_id, fae.instance_id], contributor_amounts=[2, 3])
    captured = ability.capture_event(event, GameContext(engine.state, engine.rules))
    assert captured.get("matching_ids") == [fae.instance_id]
    assert captured.get("matching_count") == 1
    assert captured.get("matching_amount") == 3


@pytest.mark.parametrize("phrase, filt", [
    ("creatures you control that entered this turn", {"card_type": "creature", "entered_this_turn": True}),
    ("goaded creatures", {"goaded": True, "card_type": "creature"}),
    ("face-down creatures you control", {"face_down": True, "card_type": "creature"}),
])
def test_state_qualifiers_on_the_subject(phrase, filt):
    head = parse_object_trigger_head(f"1 or more {phrase} deal combat damage to a player")
    assert head is not None and head.condition["filter"] == filt


def test_entered_this_turn_counts_only_new_creatures():
    engine = _engine()
    _listener(engine.state, "Whenever one or more creatures you control that entered this turn "
                            "deal combat damage to a player, draw a card.")
    veteran = _creature(engine.state, "Veteran")
    veteran.turn_entered = engine.state.internal_turn.number - 1
    _hit(engine, "p2", veteran)
    assert _hand(engine) == 0
    rookie = _creature(engine.state, "Rookie")
    rookie.turn_entered = engine.state.internal_turn.number
    _hit(engine, "p2", rookie)
    assert _hand(engine) == 1


def test_a_face_down_hitter_counts():
    engine = _engine()
    _listener(engine.state, "Whenever one or more face-down creatures you control deal combat "
                            "damage to a player, draw a card.")
    hidden = _creature(engine.state, "Hidden")
    _hit(engine, "p2", hidden)
    assert _hand(engine) == 0
    engine.rules.turn_face_down(hidden, "morph")
    _hit(engine, "p2", hidden)
    assert _hand(engine) == 1


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Alela, Cunning Conqueror", "Automated Assembly Line", "Haliya, Ascendant Cadet",
    "Invasion Tactics", "Keeper of Fables", "Olivia, Opulent Outlaw", "Prosperous Thief",
    "Thopter Spy Network", "Goro-Goro and Satoru", "Glitch Interpreter",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.full_cache
def test_prosperous_thief_makes_one_treasure_for_a_ninja_and_a_rogue():
    engine = _engine()
    _bf(engine.state, CardDatabase(DB_PATH).get_card("Prosperous Thief"))
    ninja = _creature(engine.state, "Ninja", "Human Ninja")
    rogue = _creature(engine.state, "Rogue", "Elf Rogue")
    _hit(engine, "p2", ninja, rogue)
    treasures = [o for o in engine.state.battlefield if o.card.name == "Treasure"]
    assert len(treasures) == 1
