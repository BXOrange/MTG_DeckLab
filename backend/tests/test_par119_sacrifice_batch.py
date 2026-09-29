"""PAR-119 (a) — "whenever `<a player>` sacrifices one or more `<permanents>`".

RULE 603.2c: one event, many sacrifices. `SACRIFICE` is a batched per-object event, and
the whole of an activation's or a cast's cost payment is one simultaneity scope (RULE
601.2h / 602.2b pay the total cost in one step), so "Sacrifice two creatures: …" is one
batch — as is "each player sacrifices a creature".
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.services.card_database import CardDatabase

BOSS = ("Whenever you sacrifice one or more other creatures, you gain 1 life. "
        "This ability triggers only once each turn.")


def _engine():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    engine.state.active_player_index = 0
    engine.state.current_step = "main1"
    return engine


def _bf(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _bear(state, name, owner="p1"):
    return _bf(state, Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                           power=2, toughness=2), owner)


def _parsed(state, name, type_line, oracle, owner="p1"):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    return _bf(state, card, owner)


def _cast(engine, oracle):
    you = engine.state.player_by_id("p1")
    card = Card(id="Spell", name="Spell", type_line="Sorcery", is_sorcery=True, oracle_text=oracle)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    you.hand.append(obj)
    engine.cast_spell(you, obj)
    engine.resolve_until_stable()


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond, condition", [
    ("you sacrifice 1 or more other creatures",
     {"subject": "group", "controller": "you", "other": True, "filter": {"card_type": "creature"}}),
    ("you sacrifice 1 or more foods",
     {"subject": "group", "controller": "you", "other": False, "filter": {"subtype": "food"}}),
    ("1 or more players sacrifice 1 or more creatures",
     {"subject": "group", "controller": "any", "other": False, "filter": {"card_type": "creature"}}),
    # Formerly pinned fail-closed (sacrifices paid as costs weren't one event yet).
    ("you sacrifice 2 or more creatures",
     {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}}),
])
def test_sacrifice_batch_head(cond, condition):
    head = parse_object_trigger_head(cond)
    minimum = 2 if cond.startswith("you sacrifice 2") else 1
    assert (head.event, head.condition, head.trigger) == (
        "EVENT_BATCH", condition, {"batch": {"of": "SACRIFICE", "min": minimum}})


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------


def test_a_two_creature_sacrifice_cost_is_one_batch():
    engine = _engine()
    _parsed(engine.state, "Boss", "Enchantment",
            "Whenever you sacrifice one or more other creatures, you gain 1 life.")
    altar = _parsed(engine.state, "Altar", "Artifact", "Sacrifice two creatures: Draw a card.")
    _bear(engine.state, "A")
    _bear(engine.state, "B")
    you = engine.state.player_by_id("p1")
    you.library.append(GameObject(Card(id="L", name="L", type_line="Instant"),
                                  owner_id="p1", zone=Zone.LIBRARY))
    engine.activate_ability(you, altar)
    engine.resolve_until_stable()
    assert you.life == 21
    assert sorted(o.name for o in you.graveyard) == ["A", "B"]


def test_each_player_sacrificing_is_one_batch():
    engine = _engine()
    _parsed(engine.state, "Evin", "Enchantment",
            "Whenever one or more players sacrifice one or more creatures, you gain 1 life.")
    _bear(engine.state, "Mine")
    _bear(engine.state, "Theirs", owner="p2")
    _cast(engine, "Each player sacrifices a creature.")
    assert engine.state.player_by_id("p1").life == 21


def test_an_opponents_sacrifice_is_not_yours():
    engine = _engine()
    _parsed(engine.state, "Boss", "Enchantment",
            "Whenever you sacrifice one or more creatures, you gain 1 life.")
    _bear(engine.state, "Theirs", owner="p2")
    _cast(engine, "Target opponent sacrifices a creature.")
    assert engine.state.player_by_id("p1").life == 20


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Forge Boss", "Blood Hypnotist", "Evin, Waterdeep Opportunist",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled
