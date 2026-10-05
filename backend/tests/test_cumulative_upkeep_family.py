"""Tests for MEC-16 — RULE 702.24 Cumulative Upkeep.

The keyword was already recognized by the oracle-text parser (`parser/
oracle/catalogue/keywords.py`'s catalogue table, `KeywordShape.COST`) but
never bound to any real behaviour — `game/binding/core.py`'s keyword
dispatch table had no entry for it at all, so every card printing it was
inert. This batch adds `CumulativeUpkeepEffect`/`_kw_cumulative_upkeep`:
"At the beginning of your upkeep, put an age counter on this permanent,
then sacrifice it unless you pay its upkeep cost for each age counter on
it" — reusing RULE 701.17's existing "Sacrifice ~ unless you pay `<cost>`"
pay-or-lose-it machinery (`RulesEngine._request_sacrifice_unless_pay`,
shared with ward's own cost-payment plumbing) with the parsed cost scaled
by the age-counter count.

Old Fogey (a real cached card, "Phasing, cumulative upkeep {1}, echo
{G}{G}, fading 3, …") also carries Fading, whose own upkeep trigger fires
the same event — real games always give a permanent its RULE 702.32a entry
counters when it enters, so that trigger only sacrifices a *bare*-
constructed test fixture with 0 fade counters. These tests build a
minimal synthetic Cumulative-Upkeep-only creature instead, so the
mechanic under test is isolated from that unrelated interaction; a
separate real-card test confirms Old Fogey's own clause still binds.

Reference: mtg_analyzer/game/effects/core.py (`CumulativeUpkeepEffect`,
`_scale_cumulative_upkeep_cost`), game/binding/core.py
(`_kw_cumulative_upkeep`), game/rules/misc_mixin.py
(`_request_sacrifice_unless_pay`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def filler(name="Filler"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string="{0}",
        converted_mana_cost=0, is_instant=True,
    )


def cumulative_upkeep_creature(name="Test Upkeep Creature", cost="{1}", cmc=2):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string="{1}{G}",
        converted_mana_cost=cmc, is_creature=True, power=2, toughness=2,
        oracle_text=f"Cumulative upkeep {cost}", keywords=["Cumulative upkeep"],
    )


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler("F1")] * 5), ("p2", "Bob", [filler("F2")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield_bound(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def fire_upkeep(eng, player_index=0):
    eng.state.active_player_index = player_index
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()


def test_first_upkeep_puts_one_age_counter_and_asks_to_pay_1():
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, cumulative_upkeep_creature())
    p1.mana_pool.add("C", 5)
    fire_upkeep(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "sacrifice_unless_pay"
    assert obj.counters.get("age") == 1
    eng.resolve_pending_choice("pay")
    assert p1.mana_pool.pool["C"] == 4  # {1} paid
    assert obj in eng.state.battlefield


def test_cost_scales_with_the_age_counter_count_each_upkeep():
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, cumulative_upkeep_creature())
    for expected_age, expected_cost in ((1, 1), (2, 2), (3, 3)):
        p1.mana_pool.add("C", 10)
        fire_upkeep(eng)
        before = p1.mana_pool.pool["C"]
        assert obj.counters.get("age") == expected_age
        eng.resolve_pending_choice("pay")
        assert before - p1.mana_pool.pool["C"] == expected_cost
    assert obj in eng.state.battlefield


def test_declining_sacrifices_the_permanent():
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, cumulative_upkeep_creature())
    p1.mana_pool.add("C", 5)
    fire_upkeep(eng)
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert obj not in eng.state.battlefield
    assert obj in p1.graveyard  # RULE 701.16c sacrifice, not destruction


def test_unaffordable_cost_sacrifices_outright_no_choice_offered():
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, cumulative_upkeep_creature())
    fire_upkeep(eng)  # no mana in the pool at all
    assert eng.state.pending_choice is None
    assert obj not in eng.state.battlefield
    assert obj.counters.get("age") == 1  # the age counter still went on first


def test_only_the_controllers_own_upkeep_triggers_it():
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, cumulative_upkeep_creature(), "p1")
    fire_upkeep(eng, player_index=1)  # p2's upkeep, not p1's
    assert eng.state.pending_choice is None
    assert obj.counters.get("age", 0) == 0
    assert obj in eng.state.battlefield


def test_pay_life_cost_scales_too():
    # A "pay N life" upkeep cost is printed with no brace-delimited mana
    # symbol at all ("Cumulative upkeep—Pay 1 life."), which the keyword
    # catalogue's cost-extraction regex doesn't reach (`_COST_RUN` requires
    # ``{...}`` — a real, separate, already-known parser gap, the same one
    # `parser_probe.py`'s "also blocked" bucket flags for Decomposition).
    # Built directly against `CumulativeUpkeepEffect` instead, to isolate
    # the *scaling* logic under test from that unrelated parser gap.
    from mtg_analyzer.game.effects.core import CumulativeUpkeepEffect, TriggeredAbility

    eng, p1, p2 = two_player_engine()
    blank_creature = Card(
        id="Test Life Upkeep", name="Test Life Upkeep", type_line="Creature — Bear",
        mana_cost_string="{1}{G}", converted_mana_cost=2, is_creature=True, power=2, toughness=2,
    )
    obj = battlefield_bound(eng, blank_creature)
    obj.triggered_abilities.append(
        TriggeredAbility(
            trigger_event=EventType.STEP_BEGIN,
            effects=[CumulativeUpkeepEffect(cost="Pay 1 life", source=obj)],
            condition=lambda event, context, cid=obj.controller_id: (
                event.get("step") == "upkeep"
                and getattr(getattr(context, "state", None), "active_player", None) is not None
                and context.state.active_player.id == cid
            ),
            controller_id=obj.controller_id,
            source=obj,
            description="Cumulative upkeep—Pay 1 life.",
        )
    )
    p1.life = 20
    fire_upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert p1.life == 19
    p1.life = 20
    fire_upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert p1.life == 18  # 2 age counters now → 2 life


def test_old_fogey_binds_a_real_cumulative_upkeep_trigger():
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        return
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card("Old Fogey")
    if card is None:
        return
    eng, p1, p2 = two_player_engine()
    obj = battlefield_bound(eng, card)
    descriptions = [a.description for a in obj.triggered_abilities]
    assert any("cumulative upkeep" in (d or "").lower() for d in descriptions)
