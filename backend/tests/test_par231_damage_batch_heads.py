"""PAR-231 -- "1 or more <sources> deal damage to <a player>", "~ deals damage to 1 or more <creatures>" and
"1 or more opponents are dealt noncombat damage".

RULE 120.3 / 603.2c: the damage of one simultaneous action is one batch; "to a player" triggers once for
each player hit (Francisco, Fowl Marauder's ruling), the other recipients once for the whole batch.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _creature, _put
from tests.test_par231_quantity_threshold_heads import _three_players


@pytest.mark.parametrize(
    "cond, of, recipient_keys",
    [
        ("1 or more pirates you control deal damage to a player", "DAMAGE_PER_RECIPIENT", {}),
        ("1 or more heroes you control deal noncombat damage to a player", "DAMAGE_PER_RECIPIENT", {}),
        ("1 or more pirates you control deal damage to your opponents", "DAMAGE",
         {"recipient_is_opponent": True}),
        ("1 or more opponents are dealt noncombat damage", "DAMAGE", {}),
        ("~ deals damage to 1 or more creatures", "DAMAGE", {}),
        ("~ deals combat damage to 1 or more blocking creatures", "DAMAGE", {}),
    ],
)
def test_damage_batch_grammar(cond, of, recipient_keys):
    head = parse_object_trigger_head(cond)
    assert head is not None and head.event == "EVENT_BATCH"
    assert head.trigger["batch"]["of"] == of and head.trigger["batch"]["min"] == 1
    for key, value in recipient_keys.items():
        assert head.condition[key] == value


@pytest.mark.parametrize(
    "cond",
    [
        "2 or more pirates you control deal damage to a player",  # would count events, not sources
        "~ deals damage to 2 or more creatures",
        "~ deals damage to 1 or more creatures you control",  # a recipient-controller scope is not modelled
        "1 or more pirates you control deal damage to a player and/or planeswalker",
    ],
)
def test_damage_batch_fails_closed(cond):
    head = parse_object_trigger_head(cond)
    assert head is None or head.event != "EVENT_BATCH"


@pytest.mark.parametrize(
    "name",
    ["Master of Barbs", "Briarbridge Patrol", "Arashin War Beast", "Francisco, Fowl Marauder", "The Thing, Ben Grimm"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def _counters(obj):
    return obj.counters.get("+1/+1", 0)


PIRATE_EXPLORER = "Whenever one or more Pirates you control deal damage to a player, put a +1/+1 counter on ~."


def test_one_pirate_hitting_two_players_triggers_once_for_each():
    # The ruling: damage to multiple players at once triggers once for each of those players.
    engine, state = _three_players()
    francisco = _put(state, PIRATE_EXPLORER, name="Francisco", types="Creature — Bird Pirate")
    pirates = [_creature(state, f"Pirate{i}", types="Creature — Human Pirate") for i in range(2)]
    with state.simultaneous():
        engine.rules.deal_damage(state.player_by_id("p2"), 1, source=pirates[0], combat=True)
        engine.rules.deal_damage(state.player_by_id("p2"), 1, source=pirates[1], combat=True)
        engine.rules.deal_damage(state.player_by_id("p3"), 1, source=pirates[0], combat=True)
    engine.resolve_until_stable()
    assert _counters(francisco) == 2  # two players, not three damage events


def test_a_non_pirate_or_an_opponents_pirate_does_not_trigger():
    engine, state = _three_players()
    francisco = _put(state, PIRATE_EXPLORER, name="Francisco", types="Creature — Bird Pirate")
    bear = _creature(state, "Bear")
    theirs = _creature(state, "TheirPirate", types="Creature — Human Pirate", owner="p2")
    engine.rules.deal_damage(state.player_by_id("p3"), 2, source=bear)
    engine.rules.deal_damage(state.player_by_id("p3"), 2, source=theirs)
    engine.resolve_until_stable()
    assert _counters(francisco) == 0


def test_one_opponent_batch_for_the_whole_simultaneous_damage():
    engine, state = _three_players()
    barbs = _put(state, "Whenever one or more opponents are dealt noncombat damage, put a +1/+1 counter on ~.",
                 name="Barbs")
    source = _creature(state, "Burner")
    with state.simultaneous():
        engine.rules.deal_damage(state.player_by_id("p2"), 1, source=source)
        engine.rules.deal_damage(state.player_by_id("p3"), 1, source=source)
    engine.resolve_until_stable()
    assert _counters(barbs) == 1
    engine.rules.deal_damage(state.player_by_id("p2"), 2, source=source, combat=True)
    engine.resolve_until_stable()
    assert _counters(barbs) == 1  # combat damage is not noncombat damage
    engine.rules.deal_damage(state.player_by_id("p1"), 2, source=source)
    engine.resolve_until_stable()
    assert _counters(barbs) == 1  # the controller is not an opponent


def test_self_damage_to_several_creatures_triggers_once_per_batch():
    engine, state = _three_players()
    patrol = _put(state, "Whenever ~ deals damage to one or more creatures, put a +1/+1 counter on ~.",
                  name="Patrol")
    victims = [_creature(state, f"Victim{i}", owner="p2") for i in range(3)]
    with state.simultaneous():
        for victim in victims:
            engine.rules.deal_damage(victim, 1, source=patrol)
    engine.resolve_until_stable()
    assert _counters(patrol) == 1
    engine.rules.deal_damage(state.player_by_id("p2"), 1, source=patrol)  # a player is not a creature
    engine.resolve_until_stable()
    assert _counters(patrol) == 1
