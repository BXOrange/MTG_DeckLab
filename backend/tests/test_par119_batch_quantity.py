"""PAR-119 (a) — batch quantity: "whenever one / N or more `<objects>` enter / die / leave".

RULE 603.2c: an ability triggers once per trigger event, and one event can have many
occurrences. The engine fires one per-object event per object, so `GameState.simultaneous`
groups everything one instruction (or one SBA sweep) does into an `EVENT_BATCH`, and a
batch head counts the members that match its ordinary per-object condition.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse
from mtg_analyzer.services.card_database import CardDatabase


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


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


def _listener(state, oracle):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    assert _parse(card).modeled, _parse(card).unclaimed
    return _bf(state, card)


def _library(engine, n=10):
    you = engine.state.player_by_id("p1")
    for i in range(n):
        you.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Instant"),
                                      owner_id="p1", zone=Zone.LIBRARY))
    return you


def _cast(engine, oracle):
    you = engine.state.player_by_id("p1")
    card = Card(id="Spell", name="Spell", type_line="Sorcery", is_sorcery=True, oracle_text=oracle)
    assert _parse(card).modeled, _parse(card).unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    you.hand.append(obj)
    engine.state.active_player_index = 0
    engine.state.current_step = "main1"
    engine.cast_spell(you, obj)
    engine.resolve_until_stable()


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cond, of, minimum, condition, extra", [
    ("1 or more creatures you control die", "DIES", 1,
     {"subject": "group", "controller": "you", "other": False,
      "filter": {"card_type": "creature"}}, {}),
    ("2 or more tokens you control enter", "ENTERS_BATTLEFIELD", 2,
     {"subject": "group", "controller": "you", "other": False, "filter": {"token": True}}, {}),
    ("1 or more other creatures you control leave the battlefield during your turn",
     "LEAVES_BATTLEFIELD", 1,
     {"subject": "group", "controller": "you", "other": True,
      "filter": {"card_type": "creature"}}, {"phase_relation": "you"}),
    ("3 or more creatures enter from a graveyard", "ENTERS_BATTLEFIELD", 3,
     {"subject": "group", "controller": "any", "other": False,
      "filter": {"card_type": "creature"}}, {"filter": {"from_zone": "graveyard"}}),
])
def test_batch_quantity_head(cond, of, minimum, condition, extra):
    head = parse_object_trigger_head(cond)
    assert head.event == "EVENT_BATCH"
    assert head.condition == condition
    assert head.trigger == {**extra, "batch": {"of": of, "min": minimum}}


@pytest.mark.parametrize("cond", [
    "1 or more frobnicators die",        # unknown noun
    "1 or more creatures attack alone",  # not a batched verb
    "1 or more creatures die tapped",    # unknown tail
])
def test_batch_quantity_head_fails_closed(cond):
    assert parse_object_trigger_head(cond) is None


def test_a_batch_body_gets_no_single_object_pronoun():
    card = Card(id="X", name="X", type_line="Enchantment",
                oracle_text="Whenever one or more creatures you control die, exile it.")
    assert not _parse(card).modeled


# ---------------------------------------------------------------------------
# Execute
# ---------------------------------------------------------------------------

DIES = "Whenever one or more creatures you control die, draw a card."


def test_a_board_wipe_triggers_once():
    engine = _engine()
    you = _library(engine)
    _listener(engine.state, DIES)
    for i in range(3):
        _bear(engine.state, f"Bear{i}")
    _bear(engine.state, "Theirs", owner="p2")
    _cast(engine, "Destroy all creatures.")
    assert len(you.hand) == 1


def test_separate_deaths_trigger_separately():
    engine = _engine()
    you = _library(engine)
    _listener(engine.state, DIES)
    first, second = _bear(engine.state, "A"), _bear(engine.state, "B")
    engine.rules.destroy(first)
    engine.resolve_until_stable()
    engine.rules.destroy(second)
    engine.resolve_until_stable()
    assert len(you.hand) == 2


def test_only_your_creatures_count():
    engine = _engine()
    you = _library(engine)
    _listener(engine.state, DIES)
    theirs = _bear(engine.state, "Theirs", owner="p2")
    engine.rules.destroy(theirs)
    engine.resolve_until_stable()
    assert len(you.hand) == 0


def test_the_threshold_counts_one_instruction_not_two():
    engine = _engine()
    you = _library(engine)
    _listener(engine.state, "Whenever two or more tokens you control enter, draw a card.")
    _cast(engine, "Create a 1/1 white Soldier creature token.")
    assert len(you.hand) == 0
    _cast(engine, "Create two 1/1 white Soldier creature tokens.")
    assert len(you.hand) == 1


def test_an_event_outside_any_scope_is_its_own_batch():
    engine = _engine()
    batches = []
    engine.state.subscribe(lambda e: batches.append(e) if e.type == EventType.EVENT_BATCH else None)
    lone = _bear(engine.state, "Lone")
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=lone.instance_id,
                                      controller_id="p1"))
    assert [(b.get("batch_of"), len(b.get("members"))) for b in batches] == [
        (EventType.ENTERS_BATTLEFIELD, 1)]


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Great Fierce Bee", "Welcoming Vampire", "Woodland Champion", "Cyan, Vengeful Samurai",
    "Chalk Outline", "Morbid Opportunist",
])
def test_real_cards_are_modeled(name):
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.full_cache
def test_woodland_champion_counts_that_many_tokens():
    engine = _engine()
    champion = _bf(engine.state, CardDatabase(DB_PATH).get_card("Woodland Champion"))
    _cast(engine, "Create three 1/1 green Saproling creature tokens.")
    assert champion.counters.get("+1/+1") == 3


@pytest.mark.full_cache
@pytest.mark.parametrize("types, expected", [("Creature — Bear", 1), ("Instant", 0)])
def test_cyan_counts_only_creature_cards_leaving_your_graveyard(types, expected):
    engine = _engine()
    cyan = _bf(engine.state, CardDatabase(DB_PATH).get_card("Cyan, Vengeful Samurai"))
    you = engine.state.player_by_id("p1")
    card = GameObject(Card(id="G", name="G", type_line=types, is_creature="Creature" in types,
                           power=1 if "Creature" in types else None,
                           toughness=1 if "Creature" in types else None),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    you.graveyard.append(card)
    engine.rules.exile(card)
    engine.resolve_until_stable()
    assert cyan.counters.get("+1/+1", 0) == expected


@pytest.mark.full_cache
def test_frantic_scapegoat_offers_only_the_creatures_that_just_entered():
    engine = _engine()
    scapegoat = _bf(engine.state, CardDatabase(DB_PATH).get_card("Frantic Scapegoat"))
    engine.rules.suspect(scapegoat)
    _bear(engine.state, "Older")  # already on the battlefield: not "one of the other creatures"
    _cast(engine, "Create two 1/1 white Soldier creature tokens.")
    choice = engine.state.pending_choice
    assert choice["kind"] == "choose_objects"
    offered = [option["label"] for option in choice["options"] if option.get("instance_id")]
    assert offered == ["Soldier", "Soldier"]


# ---------------------------------------------------------------------------
# Discard batches, and a multi-pick choice held open as one event
# ---------------------------------------------------------------------------

DISCARD = "Whenever you discard one or more cards, you gain that much life."


def _hand(engine, n):
    you = engine.state.player_by_id("p1")
    for i in range(n):
        you.hand.append(GameObject(Card(id=f"H{i}", name=f"H{i}", type_line="Instant"),
                                   owner_id="p1", zone=Zone.HAND))
    return you


def test_you_discard_n_or_more_head():
    head = parse_object_trigger_head("you discard 1 or more artifact cards")
    assert head.event == "EVENT_BATCH"
    assert head.condition == {"subject": "group", "controller": "you", "other": False,
                              "filter": {"card_type": "artifact"}}
    assert head.trigger == {"batch": {"of": "DISCARD_CARD", "min": 1}}


def test_a_two_card_discard_triggers_once_with_that_many():
    engine = _engine()
    you = _hand(engine, 3)
    _listener(engine.state, DISCARD)
    engine.rules.discard(you, 2)
    engine.resolve_until_stable()
    assert you.life == 22


def _answer_all(engine):
    while engine.state.pending_choice and engine.state.pending_choice["kind"] == "choose_objects":
        pick = next(o for o in engine.state.pending_choice["options"] if o.get("instance_id"))
        engine.rules._resume_choose_objects(engine.state.pending_choice, pick["instance_id"])
    engine.resolve_until_stable()


def test_an_interactive_two_card_discard_is_still_one_event():
    # Counted by triggers, not by "that much": two 1-card batches would gain the same 2.
    engine = _engine()
    _library(engine)
    you = _hand(engine, 3)
    _listener(engine.state, "Whenever you discard one or more cards, draw a card.")
    engine.rules.discard_choice(you, 2)
    _answer_all(engine)
    assert len(you.graveyard) == 2
    assert len(you.hand) == 2  # 3 - 2 discarded + 1 drawn, once


def test_an_interactive_two_creature_sacrifice_is_one_death_batch():
    engine = _engine()
    you = _library(engine)
    _listener(engine.state, DIES)
    for name in ("A", "B", "C"):
        _bear(engine.state, name)
    engine.rules.sacrifice(you, "creature", 2)
    _answer_all(engine)
    assert len(you.graveyard) == 2
    assert len(you.hand) == 1
