"""Tests for variable-count "remove a counter" activation costs (RULE
602.1/601.2b) — "Remove X counters" (Arcbound Javelineer/Chamber Sentry/
Marath/the storage-land cycle/the Baku cycle-shaped) and "Remove any number
of counters" (the Mana Battery cycle/more storage lands/Geistflame
Reservoir-shaped), both announced via the same ``x`` parameter
`activate_ability` already threads through for mana ``{X}``
(`REMOVE_COUNTERS_X`/`REMOVE_COUNTERS_ANY`, mirroring `PAY_LIFE_X`'s
sentinel idiom).

A live query against the cached Oracle DB confirmed the ToDo backlog's other
two phrasings ("remove up to N counters"/"remove all counters from all
permanents") are actually resolution *effects* on every real card found,
never activation costs — see `tests/test_remove_counters_effect.py`.
"""

from mtg_analyzer.game.costs import (
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    parse_activation_cost,
)
from mtg_analyzer.game.effects import ActivatedAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def make_engine(hand=0):
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6)]
    return GameEngine.new_game([("p1", "Alice", cards)], starting_life=20, starting_hand=hand)


# ---------------------------------------------------------------------------
# Cost-string recognition (game/costs.py)
# ---------------------------------------------------------------------------


def test_remove_x_counters_is_recognized():
    # Blademane Baku-shaped — no {X} mana at all, X announced purely by
    # this cost clause.
    cost = parse_activation_cost("{1}, Remove X ki counters from this creature")
    assert cost.remove_counters == ("ki", REMOVE_COUNTERS_X)


def test_remove_x_plus_one_plus_one_counters_is_recognized():
    # Chamber Sentry-shaped — the same announced X also pays the {X} mana.
    cost = parse_activation_cost("{X}, {T}, Remove X +1/+1 counters from this creature")
    assert cost.remove_counters == ("+1/+1", REMOVE_COUNTERS_X)
    assert cost.mana.has_variable is True


def test_remove_any_number_of_counters_is_recognized():
    # The Mana Battery cycle.
    cost = parse_activation_cost("{T}, Remove any number of charge counters from this artifact")
    assert cost.remove_counters == ("charge", REMOVE_COUNTERS_ANY)


def test_remove_fixed_count_still_works_unchanged():
    # Pre-existing shape (RULE 701.19) must stay unaffected.
    cost = parse_activation_cost("Remove a +1/+1 counter from ~")
    assert cost.remove_counters == ("+1/+1", 1)
    cost3 = parse_activation_cost("Remove three loyalty counters")
    assert cost3.remove_counters == ("loyalty", 3)


def test_remove_x_counters_label():
    cost = parse_activation_cost("{1}, Remove X ki counters from this creature")
    assert "Remove X ki counter(s)" in cost.label()


def test_remove_any_number_label():
    cost = parse_activation_cost("{T}, Remove any number of charge counters from this artifact")
    assert "Remove any number of charge counters" in cost.label()


# ---------------------------------------------------------------------------
# ENGINE: can_activate / activate_ability with an announced x
# ---------------------------------------------------------------------------


def _permanent_with_counters(engine, kind="ki", amount=3):
    card = Card(id="Baku", name="Baku", type_line="Creature", is_creature=True,
                power=2, toughness=2)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.counters[kind] = amount
    engine.state.add_to_battlefield(obj)
    ability = ActivatedAbility(
        effects=[],
        cost=parse_activation_cost("Remove X ki counters from this creature"),
        source=obj,
    )
    obj.activated_abilities.append(ability)
    return obj, ability


def test_cannot_activate_for_more_x_than_available_counters():
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    obj, ability = _permanent_with_counters(eng, amount=2)
    assert eng.can_activate(p1, obj, ability, x=3) is False
    assert eng.can_activate(p1, obj, ability, x=2) is True


def test_activating_for_x_removes_exactly_that_many_counters():
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    obj, ability = _permanent_with_counters(eng, amount=3)
    eng.activate_ability(p1, obj, 0, x=2)
    assert obj.counters.get("ki", 0) == 1


def test_activating_for_x_zero_is_legal_and_removes_none():
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    obj, ability = _permanent_with_counters(eng, amount=3)
    eng.activate_ability(p1, obj, 0, x=0)
    assert obj.counters.get("ki", 0) == 3


def test_legal_action_reports_max_x_bounded_by_available_counters_with_no_x_mana():
    # Blademane Baku has no {X} mana symbol — has_x/max_x must still be
    # offered, bounded purely by the counters on the permanent.
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    obj, ability = _permanent_with_counters(eng, amount=4)
    [action] = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "activate_ability" and a.get("instance_id") == obj.instance_id
    ]
    assert action["has_x"] is True
    assert action["max_x"] == 4


def test_legal_action_max_x_is_the_stricter_of_mana_and_counters_bounds():
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    card = Card(id="Chamber Sentry", name="Chamber Sentry", type_line="Artifact Creature",
                is_creature=True, power=0, toughness=4)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.counters["+1/+1"] = 5
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    ability = ActivatedAbility(
        effects=[],
        cost=parse_activation_cost("{X}, {T}, Remove X +1/+1 counters from this creature"),
        source=obj,
    )
    obj.activated_abilities.append(ability)
    p1.mana_pool.add_many({"C": 2})  # only enough mana for X=2, though 5 counters exist
    [action] = [
        a for a in eng.legal_actions(p1)
        if a.get("type") == "activate_ability" and a.get("instance_id") == obj.instance_id
    ]
    assert action["has_x"] is True
    assert action["max_x"] == 2


def test_any_number_of_counters_cost_allows_zero_and_any_amount_up_to_available():
    eng = make_engine(hand=0)
    p1 = eng.state.active_player
    card = Card(id="Blue Mana Battery", name="Blue Mana Battery", type_line="Artifact")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.counters["charge"] = 3
    eng.state.add_to_battlefield(obj)
    ability = ActivatedAbility(
        effects=[],
        cost=parse_activation_cost("{T}, Remove any number of charge counters from this artifact"),
        source=obj,
    )
    obj.activated_abilities.append(ability)
    assert eng.can_activate(p1, obj, ability, x=0) is True
    assert eng.can_activate(p1, obj, ability, x=3) is True
    assert eng.can_activate(p1, obj, ability, x=4) is False
    eng.activate_ability(p1, obj, 0, x=2)
    assert obj.counters.get("charge", 0) == 1
