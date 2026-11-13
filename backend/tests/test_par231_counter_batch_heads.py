"""PAR-231 -- counter-batch heads: "you put <n> or more <kind> counters on <obj>" and
"<n> or more <kind> counters are removed from ~".

RULE 122.6 / 603.2c: one placement or removal is one event however many counters it covers, so a threshold
compares that event's ``amount``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_attack_batch_head import _stocked
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _creature, _put


@pytest.mark.parametrize(
    "cond, event, condition, filt",
    [
        ("you put 2 or more +1/+1 counters on a creature you control", "COUNTER",
         {"subject": "group", "controller": "you", "other": False, "filter": {"card_type": "creature"}},
         {"kind": "+1/+1", "by_you": True, "event_minimums": {"amount": 2}}),
        ("you put 1 or more -1/-1 counters on ~", "COUNTER", {"subject": "self"},
         {"kind": "-1/-1", "by_you": True}),
        ("2 or more time counters are removed from ~", "COUNTERS_REMOVED", {"subject": "self"},
         {"kind": "time", "event_minimums": {"amount": 2}}),
        ("1 or more loyalty counters are removed from ~", "COUNTERS_REMOVED", {"subject": "self"},
         {"kind": "loyalty"}),
    ],
)
def test_counter_batch_grammar(cond, event, condition, filt):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == event
    assert head.condition == condition
    assert head.trigger["filter"] == filt


@pytest.mark.parametrize(
    "cond",
    [
        "you put 2 or more +1/+1 counters on 2 or more other heroes you control",
        "you put 2 or more frobnicating counters on target creature",
        "2 or more time counters are removed from target permanent",
    ],
)
def test_counter_batch_fails_closed(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or head.event not in ("COUNTERS_REMOVED",) and "by_you" not in head.trigger.get("filter", {})


@pytest.mark.parametrize(
    "name",
    ["Defiant Greatmaw", "Inspired Tethermage", "Nest of Scarabs", "Regenerations Restored", "Stocking the Pantry",
     "Terrasymbiosis"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

NEST = "Whenever you put 1 or more -1/-1 counters on a creature, create that many 1/1 black Insect creature tokens."
GAIN_ON_TWO = "Whenever you put 2 or more +1/+1 counters on a creature you control, you gain 3 life."


def _insects(state):
    return [o for o in state.battlefield if "Insect" in (o.card.type_line or "")]


def test_nest_of_scarabs_makes_one_insect_per_counter_put_in_one_placement():
    engine, state = _stocked()
    nest = _put(state, NEST, name="Nest", types="Enchantment")
    victim = _creature(state, "Victim", owner="p2")
    engine.rules.add_counters(victim, 3, "-1/-1", source=nest)
    engine.resolve_until_stable()
    assert len(_insects(state)) == 3  # one trigger, three counters (RULE 122.6)


def test_a_threshold_ignores_a_smaller_placement_and_a_placement_by_an_opponent():
    engine, state = _stocked()
    source = _put(state, GAIN_ON_TWO, name="Gain", types="Enchantment")
    mine = _creature(state, "Mine")
    p1 = state.player_by_id("p1")
    start = p1.life
    engine.rules.add_counters(mine, 1, "+1/+1", source=source)
    engine.resolve_until_stable()
    assert p1.life == start  # one counter is below the threshold
    opposing = _put(state, "", name="Theirs", types="Enchantment", owner="p2")
    engine.rules.add_counters(mine, 2, "+1/+1", source=opposing)
    engine.resolve_until_stable()
    assert p1.life == start  # an opponent's effect is not "you put"
    engine.rules.add_counters(mine, 2, "+1/+1", source=source)
    engine.resolve_until_stable()
    assert p1.life == start + 3


def test_the_recipient_scope_is_enforced():
    engine, state = _stocked()
    source = _put(state, GAIN_ON_TWO, name="Gain", types="Enchantment")
    theirs = _creature(state, "Theirs", owner="p2")
    p1 = state.player_by_id("p1")
    start = p1.life
    engine.rules.add_counters(theirs, 2, "+1/+1", source=source)
    engine.resolve_until_stable()
    assert p1.life == start  # "a creature you control"


REMOVED = "Whenever 2 or more time counters are removed from ~, you gain 3 life."


def test_counters_removed_threshold_fires_once_per_removal():
    engine, state = _stocked()
    permanent = _put(state, REMOVED, name="Clock", types="Enchantment")
    permanent.add_counters("time", 5)
    p1 = state.player_by_id("p1")
    start = p1.life
    engine.rules.add_counters(permanent, -1, "time")
    engine.resolve_until_stable()
    assert p1.life == start  # one counter off: below the threshold
    engine.rules.add_counters(permanent, -3, "time")
    engine.resolve_until_stable()
    assert p1.life == start + 3  # three counters in one removal: one trigger


def test_loyalty_cost_counts_as_putting_and_removing_loyalty_counters():
    engine, state = _stocked()
    p1 = state.player_by_id("p1")
    _put(state, "Whenever you put 1 or more loyalty counters on a planeswalker, you gain 1 life.",
         name="Tether", types="Creature — Wizard")
    walker = _put(state, "Whenever 2 or more loyalty counters are removed from ~, you gain 5 life.",
                  name="Walker", types="Legendary Planeswalker")
    walker.add_counters("loyalty", 5)
    start = p1.life
    engine._pay_loyalty_cost(walker, 1)
    engine.resolve_until_stable()
    assert p1.life == start + 1
    engine._pay_loyalty_cost(walker, -3)
    engine.resolve_until_stable()
    assert p1.life == start + 1 + 5


# ---------------------------------------------------------------------------
# "whenever 1 or more nonland cards are milled" (RULE 701.13 / 603.2c)
# ---------------------------------------------------------------------------

MILL_DRAW = "Whenever one or more nonland cards are milled, draw a card."


def _library(state, owner, kinds):
    player = state.player_by_id(owner)
    for i, type_line in enumerate(kinds):
        player.library.append(GameObject(Card(id=f"{owner}{i}", name=f"{owner}{i}", type_line=type_line),
                                         owner_id=owner, zone=Zone.LIBRARY))
    return player


def test_nonland_milled_head_parses_and_fails_closed():
    assert parse_oracle(_named("Mirelurk Queen")).modeled is True
    assert parse_oracle(_named("Screeching Scorchbeast")).modeled is False  # "that many" body not modelled


def test_nonland_milled_fires_once_for_any_players_mill_with_a_nonland_card():
    engine, state = _stocked()
    _put(state, MILL_DRAW, name="Queen", types="Enchantment")
    p1 = state.player_by_id("p1")
    victim = _library(state, "p2", ["Creature — Bear", "Land", "Instant"])
    before = len(p1.hand)
    engine.rules.mill(victim, 3)
    engine.resolve_until_stable()
    assert len(p1.hand) - before == 1  # an opponent's mill, two nonland cards, one trigger


def test_a_mill_of_only_lands_does_not_trigger_it():
    engine, state = _stocked()
    _put(state, MILL_DRAW, name="Queen", types="Enchantment")
    p1 = state.player_by_id("p1")
    victim = _library(state, "p2", ["Land", "Basic Land — Forest"])
    before = len(p1.hand)
    engine.rules.mill(victim, 2)
    engine.resolve_until_stable()
    assert len(p1.hand) == before


def test_mirelurk_queen_triggers_once_each_turn():
    engine, state = _stocked()
    _put(state, "Whenever one or more nonland cards are milled, draw a card. This ability triggers only once each turn.",
         name="Queen", types="Enchantment")
    p1 = state.player_by_id("p1")
    victim = _library(state, "p2", ["Creature — Bear", "Instant", "Sorcery"])
    before = len(p1.hand)
    engine.rules.mill(victim, 1)
    engine.rules.mill(victim, 1)
    engine.resolve_until_stable()
    assert len(p1.hand) - before == 1
