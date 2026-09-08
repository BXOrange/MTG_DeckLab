"""PAR-29 — RULE 701.56 Time Travel (Doctor Who).

`RulesEngine.time_travel(player, times)` — documented simplification (no
per-object add/remove choice): a suspended card `player` owns loses one
time counter (and opens the RULE 702.62a free-cast window if that empties
it); a Vanishing/Fading-style permanent `player` controls gains one.
`effects.TimeTravelEffect` binds a bare "time travel" clause; "time
travel, then time travel" is two of them.

Reference: game/rules/misc_mixin.py (`time_travel`), game/effects/core.py
(`TimeTravelEffect`), parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_time_travel_clause():
    assert match_clause("time travel") == [EffectSpec("time_travel", {})]
    assert match_clause("you time travel") == [EffectSpec("time_travel", {})]


def test_real_time_travel_cards_modeled():
    beetle = Card(id="TB", name="Time Beetle", type_line="Creature — Insect",
                  is_creature=True, power=1, toughness=1,
                  oracle_text="Whenever this creature deals combat damage to a "
                              "player, time travel.")
    assert parse_oracle(beetle).modeled, parse_oracle(beetle).unclaimed
    wib = Card(id="WW", name="Wibbly-wobbly, Timey-wimey",
               type_line="Legendary Sorcery", is_sorcery=True,
               oracle_text="Time travel.\nDraw a card.")
    assert parse_oracle(wib).modeled, parse_oracle(wib).unclaimed


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def test_time_travel_accelerates_a_suspended_card():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    susp = Card(id="S", name="Suspended Bolt", type_line="Instant", is_instant=True,
               oracle_text="Suspend 3—{R}\nSuspended Bolt deals 3 damage to any target.",
               keywords=["Suspend"])
    o = GameObject(susp, owner_id="p1", zone=Zone.EXILE)
    o.parametric_keywords = {"suspend": {"n": 3, "cost": "{R}"}}
    o.add_counters("time", 3)
    p1.exile.append(o)

    eng.rules.time_travel(p1)
    assert o.counters.get("time", 0) == 2

    eng.rules.time_travel(p1, times=2)
    assert o.counters.get("time", 0) == 0
    # emptied -> the free-cast window opened (RULE 702.62a)
    assert o.instance_id in st.free_cast_instance_ids


def test_time_travel_prolongs_a_vanishing_permanent():
    eng = _engine()
    st = eng.state
    p1 = st.player_by_id("p1")
    van = GameObject(
        Card(id="V", name="Vanishing Bear", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2, keywords=["Vanishing"]),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    van.controller_id = "p1"
    van.add_counters("time", 1)
    st.add_to_battlefield(van)

    eng.rules.time_travel(p1)
    assert van.counters.get("time", 0) == 2   # gained one, still alive
    assert van in st.battlefield
