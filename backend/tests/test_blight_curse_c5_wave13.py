"""Blight Curse batch C5 wave 13 — Eventide's Shadow
(hand-authored, `ability_catalogue/entries_017.py`).

New bespoke `RemoveCountersFromAmongThenDrawLoseLifeEffect`
("remove_counters_from_among_then_draw_lose_life"): an ``optional``
`request_choose_objects` over counter-bearing permanents (new action
``strip_all_counters``), then a draw + life loss equal to the battlefield
counter-total delta (`DrawLoseLifeCounterRemovedDeltaEffect`).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


EVENTIDES_SHADOW = Card(
    id="EVS", name="Eventide's Shadow", type_line="Sorcery", is_sorcery=True,
    mana_cost_string="{4}{B}", converted_mana_cost=5,
    oracle_text="Remove any number of counters from among permanents on the battlefield. "
                "You draw cards and lose life equal to the number of counters removed this way.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _src(eng):
    o = GameObject(EVENTIDES_SHADOW, owner_id="p1", zone=Zone.STACK)
    o.controller_id = "p1"
    bind_from_catalogue(o)
    return o


def _bf(eng, cid, ctrl, **counters):
    o = GameObject(Card(id=cid, name=cid, type_line="Creature — Ox", is_creature=True,
                        power=2, toughness=2), owner_id=ctrl, zone=Zone.BATTLEFIELD)
    o.controller_id = ctrl
    for k, v in counters.items():
        o.counters[{"plus": "+1/+1", "minus": "-1/-1"}.get(k, k)] = v
    eng.state.add_to_battlefield(o)
    return o


def _stock_library(eng, pid, n):
    pl = next(p for p in eng.state.players if p.id == pid)
    for i in range(n):
        pl.library.append(GameObject(Card(id=f"L{pid}{i}", name=f"L{pid}{i}", type_line="Island",
                                          is_land=True), owner_id=pid, zone=Zone.LIBRARY))
    return pl


def test_eventides_shadow_authored():
    specs = specs_for(EVENTIDES_SHADOW)
    assert len(specs) == 1
    assert specs[0].effects[0].type == "remove_counters_from_among_then_draw_lose_life"


def test_removing_from_all_counter_bearers_draws_and_drains_the_total():
    eng = _engine()
    p1 = _stock_library(eng, "p1", 10)
    a = _bf(eng, "A", "p1", minus=3)
    b = _bf(eng, "B", "p2", plus=2)
    _bf(eng, "C", "p1")  # no counters -> not a candidate
    src = _src(eng)
    eng.begin_turn()
    life0 = p1.life

    build_effects([EffectSpec("remove_counters_from_among_then_draw_lose_life", {})], src)[0] \
        .apply(GameContext(eng.state, eng.rules), targets=None)

    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "choose_objects"
    assert {o.get("instance_id") for o in pc["options"] if o.get("instance_id")} == {a.instance_id, b.instance_id}
    eng.rules.resolve_choose_objects_choice(a.instance_id)
    eng.rules.resolve_choose_objects_choice(b.instance_id)
    eng.resolve_until_stable()

    assert not a.counters and not b.counters
    assert len(p1.hand) == 5          # 3 + 2 removed
    assert p1.life == life0 - 5


def test_partial_selection_then_decline():
    eng = _engine()
    p1 = _stock_library(eng, "p1", 10)
    a = _bf(eng, "A", "p1", minus=3)
    _bf(eng, "B", "p2", plus=2)
    src = _src(eng)
    eng.begin_turn()
    life0 = p1.life

    build_effects([EffectSpec("remove_counters_from_among_then_draw_lose_life", {})], src)[0] \
        .apply(GameContext(eng.state, eng.rules), targets=None)

    eng.rules.resolve_choose_objects_choice(a.instance_id)   # strip A (3)
    eng.rules.resolve_choose_objects_choice(None)            # decline the rest
    eng.resolve_until_stable()

    assert not a.counters
    assert len(p1.hand) == 3
    assert p1.life == life0 - 3


def test_declining_immediately_is_a_noop():
    eng = _engine()
    p1 = _stock_library(eng, "p1", 10)
    _bf(eng, "A", "p1", minus=3)
    src = _src(eng)
    eng.begin_turn()
    life0 = p1.life

    build_effects([EffectSpec("remove_counters_from_among_then_draw_lose_life", {})], src)[0] \
        .apply(GameContext(eng.state, eng.rules), targets=None)
    eng.rules.resolve_choose_objects_choice(None)
    eng.resolve_until_stable()

    assert not p1.hand and p1.life == life0


def test_no_counters_anywhere_is_a_noop():
    eng = _engine()
    p1 = _stock_library(eng, "p1", 5)
    _bf(eng, "A", "p1")
    src = _src(eng)
    eng.begin_turn()

    build_effects([EffectSpec("remove_counters_from_among_then_draw_lose_life", {})], src)[0] \
        .apply(GameContext(eng.state, eng.rules), targets=None)

    assert eng.state.pending_choice is None
    assert not p1.hand and p1.life == 20
