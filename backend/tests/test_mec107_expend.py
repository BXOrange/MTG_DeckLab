"""MEC-107 — Expend (RULE 700.14): "Whenever you expend N."

A player expends N when paying a spell's cost takes the mana they have spent on
spells this turn from below N to at least N. The engine derives the running total
from the turn's `SPELL_CAST.mana_spent` events and fires one `EXPEND` event per N
crossed; the parser reads "you expend N" as an `EXPEND` head filtered on ``amount``.

Parse tests pin the grammar; execute tests cast real spells through `cast_spell`
with a real mana pool and watch a real listener resolve.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.player_event_head import parse_player_event_head

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


def test_head_reads_the_threshold_as_an_exact_amount_filter():
    assert parse_player_event_head("you expend 4") == (
        "EXPEND", {"subject": "you"}, {"filter": {"amount": 4}},
    )
    assert parse_player_event_head("you expend 8")[2] == {"filter": {"amount": 8}}


@pytest.mark.parametrize("phrase", ["you expend", "you expend four", "you expend 4 or more"])
def test_head_fails_closed_on_a_phrase_it_does_not_own(phrase):
    assert parse_player_event_head(phrase) is None


def _card(name, oracle, type_line="Creature — Raccoon", **kw):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                is_creature="Creature" in type_line, power=2, toughness=2, **kw)


@pytest.mark.parametrize(
    "oracle",
    [
        "Whenever you expend 4, this creature deals 2 damage to each opponent.",
        "Whenever you expend 4, put a +1/+1 counter on this creature.",
        "Whenever you expend 8, return up to one target permanent card from your graveyard to your hand.",
    ],
)
def test_expend_triggers_are_modeled(oracle):
    result = parse_oracle(_card("Expender", oracle))
    assert result.modeled, result.unclaimed
    (spec,) = [s for s in result.specs if s.ability_kind == "triggered"]
    assert spec.trigger["event"] == "EXPEND"
    assert spec.trigger["filter"]["amount"] in (4, 8)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _engine():
    engine = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine


def _listener(engine, oracle, controller="p1"):
    card = Card(id="Listener", name="Listener", type_line="Enchantment", oracle_text=oracle)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _spell(engine, cost, player="p1", name=None):
    """A vanilla sorcery-speed-free instant of the given printed cost, in hand."""
    name = name or f"Spell {cost}"
    card = Card(
        id=name, name=name, type_line="Instant", is_instant=True, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
    )
    obj = GameObject(card, owner_id=player, zone=Zone.HAND)
    engine.state.player_by_id(player).hand.append(obj)
    return obj


def _cast(engine, cost, player="p1"):
    who = engine.state.player_by_id(player)
    who.mana_pool.add("C", ManaCost.parse(cost).converted_mana_cost)
    engine.cast_spell(who, _spell(engine, cost, player))
    engine.resolve_until_stable()


def _expend_events(engine, player="p1"):
    return [
        e.get("amount") for e in engine.state.event_log
        if e.type == EventType.EXPEND and e.get("player_id") == player
    ]


LIFE = "you gain 1 life."


def test_expend_four_fires_on_the_cast_that_crosses_it_not_before():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    life = engine.state.player_by_id("p1").life

    _cast(engine, "{2}")  # 2 spent this turn: below 4
    assert engine.state.player_by_id("p1").life == life

    _cast(engine, "{3}")  # 2 -> 5: crosses 4
    assert engine.state.player_by_id("p1").life == life + 1
    assert _expend_events(engine) == [1, 2, 3, 4, 5]  # 1-2 on the first cast, 3-5 on the second


def test_a_threshold_is_expended_once_per_turn():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    life = engine.state.player_by_id("p1").life
    _cast(engine, "{4}")
    _cast(engine, "{2}")  # already past 4: crossing nothing new
    assert engine.state.player_by_id("p1").life == life + 1


def test_one_big_payment_crosses_every_threshold_at_once():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    _listener(engine, f"Whenever you expend 8, {LIFE}")
    life = engine.state.player_by_id("p1").life
    _cast(engine, "{9}")
    assert engine.state.player_by_id("p1").life == life + 2


def test_exact_threshold_counts_as_at_least_n():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    life = engine.state.player_by_id("p1").life
    _cast(engine, "{4}")
    assert engine.state.player_by_id("p1").life == life + 1


def test_expend_has_no_artificial_threshold_ceiling():
    engine = _engine()
    _listener(engine, f"Whenever you expend 41, {LIFE}")
    life = engine.state.player_by_id("p1").life
    _cast(engine, "{41}")
    assert engine.state.player_by_id("p1").life == life + 1
    assert 41 in _expend_events(engine)


def test_an_opponents_spending_does_not_count_for_you():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    life = engine.state.player_by_id("p1").life
    engine.state.player_by_id("p2").mana_pool.add("C", 5)
    engine.cast_spell(engine.state.player_by_id("p2"), _spell(engine, "{5}", "p2"))
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p1").life == life
    assert _expend_events(engine, "p2") == [1, 2, 3, 4, 5]
    assert _expend_events(engine, "p1") == []


def test_a_free_cast_spends_no_mana_and_expends_nothing():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    life = engine.state.player_by_id("p1").life
    spell = _spell(engine, "{6}")
    engine.rules.cast_without_paying(engine.state.player_by_id("p1"), spell)
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p1").life == life
    assert _expend_events(engine) == []


def test_the_total_resets_with_the_turn():
    engine = _engine()
    _listener(engine, f"Whenever you expend 4, {LIFE}")
    _cast(engine, "{3}")
    engine.state.internal_turn.number += 1  # a new turn: last turn's spending is history
    life = engine.state.player_by_id("p1").life
    _cast(engine, "{3}")  # 3 this turn, not 6
    assert engine.state.player_by_id("p1").life == life
