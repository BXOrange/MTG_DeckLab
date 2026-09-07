"""Blight Curse batch C5 wave 10 — Ferrafor, Young Yew
(hand-authored, `ability_catalogue/entries_017.py`).

* ETB — new `CreateTokensPerCounterAmongTargetPlayerCreaturesEffect`: create
  N 1/1 green Saproling tokens, N = every counter on every creature the
  chosen player controls.
* {T} — new reusable `DoubleCountersOnTargetEffect` (RULE 701.19): for each
  kind of counter on target creature, put that many more on it.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


FERRAFOR = Card(
    id="FYY", name="Ferrafor, Young Yew", type_line="Legendary Creature — Treefolk Druid",
    is_creature=True, power=6, toughness=7,
    oracle_text="When Ferrafor enters, create a number of 1/1 green Saproling creature "
                "tokens equal to the number of counters among creatures target player "
                "controls.\n{T}: Double the number of each kind of counter on target creature.",
)


def _bf(eng, card, controller, **counters):
    o = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    o.controller_id = controller
    for k, v in counters.items():
        o.counters[k.replace("plus", "+1/+1").replace("minus", "-1/-1")] = v
    eng.state.add_to_battlefield(o)
    return o


def test_ferrafor_authored_two_clauses():
    specs = specs_for(FERRAFOR)
    assert {s.ability_kind for s in specs} == {"triggered", "activated"}
    act = [s for s in specs if s.ability_kind == "activated"][0]
    assert act.effects[0].type == "double_counters_on_target"


def test_double_counters_doubles_each_kind():
    eng = _engine()
    ferra = _bf(eng, FERRAFOR, "p1")
    bind_from_catalogue(ferra)
    target = _bf(eng, Card(id="T", name="T", type_line="Creature — Ox", is_creature=True,
                           power=2, toughness=2), "p1")
    target.counters["+1/+1"] = 3
    target.counters["charge"] = 1

    eff = build_effects([EffectSpec("double_counters_on_target", {"target_kind": "creature"})], ferra)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[target])
    eng.recompute_continuous_effects()

    assert target.counters.get("+1/+1") == 6
    assert target.counters.get("charge") == 2
    assert (target.power, target.toughness) == (8, 8)


def test_double_counters_noop_when_target_has_none():
    eng = _engine()
    ferra = _bf(eng, FERRAFOR, "p1")
    bind_from_catalogue(ferra)
    bare = _bf(eng, Card(id="B", name="B", type_line="Creature — Ox", is_creature=True,
                         power=2, toughness=2), "p1")
    eff = build_effects([EffectSpec("double_counters_on_target", {})], ferra)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[bare])
    assert not bare.counters


def test_etb_creates_saprolings_equal_to_counters_among_target_players_creatures():
    eng = _engine()
    ferra = _bf(eng, FERRAFOR, "p1")
    bind_from_catalogue(ferra)
    # p2's creatures carry 2 + 1 + 3 = 6 counters total
    a = _bf(eng, Card(id="A", name="A", type_line="Creature — Rat", is_creature=True,
                      power=1, toughness=1), "p2")
    a.counters["-1/-1"] = 2
    a.counters["charge"] = 1
    b = _bf(eng, Card(id="C", name="C", type_line="Creature — Rat", is_creature=True,
                      power=1, toughness=1), "p2")
    b.counters["+1/+1"] = 3
    # p1's own creature counters must NOT be counted
    mine = _bf(eng, Card(id="M", name="M", type_line="Creature — Ox", is_creature=True,
                         power=2, toughness=2), "p1")
    mine.counters["+1/+1"] = 5

    p2 = eng.state.players[1]
    eff = build_effects([EffectSpec(
        "create_tokens_per_counter_among_target_player_creatures",
        {"power": 1, "toughness": 1, "colors": ["G"], "subtypes": ["Saproling"],
         "token_name": "Saproling"},
    )], ferra)[0]
    before = sum(1 for o in eng.state.battlefield
                 if getattr(o.card, "name", "") == "Saproling")
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])

    saprolings = [o for o in eng.state.battlefield
                  if getattr(o.card, "name", "") == "Saproling"]
    assert len(saprolings) - before == 6
    assert all(o.controller_id == "p1" for o in saprolings)


def test_etb_creates_nothing_when_target_player_has_no_counters():
    eng = _engine()
    ferra = _bf(eng, FERRAFOR, "p1")
    bind_from_catalogue(ferra)
    _bf(eng, Card(id="A", name="A", type_line="Creature — Rat", is_creature=True,
                  power=1, toughness=1), "p2")
    p2 = eng.state.players[1]
    eff = build_effects([EffectSpec(
        "create_tokens_per_counter_among_target_player_creatures", {},
    )], ferra)[0]
    eff.apply(GameContext(eng.state, eng.rules), targets=[p2])
    saprolings = [o for o in eng.state.battlefield
                  if getattr(o.card, "name", "") == "Saproling"]
    assert not saprolings
