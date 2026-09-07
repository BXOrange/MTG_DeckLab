"""Blight Curse batch C5 wave 6 — Kulrath Knight
(hand-authored, `ability_catalogue/entries_017.py`).

* Kulrath Knight — "Creatures your opponents control with counters on them
  can't attack or block." A layer-6 ``grant_keyword`` static handing the
  synthetic ``cant_attack`` / ``cant_block`` flag keywords to the new
  ``creatures_opponents_control_with_a_counter`` affected set
  (`game/continuous.affected_objects`). Flying + Wither fold in as keywords.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


KULRATH_KNIGHT = Card(
    id="KK", name="Kulrath Knight", type_line="Creature — Elemental Knight",
    is_creature=True, power=3, toughness=3, keywords=["Flying", "Wither"],
    oracle_text="Flying\nWither (This deals damage to creatures in the form of -1/-1 "
                "counters.)\nCreatures your opponents control with counters on them "
                "can't attack or block.",
)


def test_kulrath_knight_authored_single_static():
    specs = specs_for(KULRATH_KNIGHT)
    stat = [s for s in specs if s.ability_kind == "static"]
    assert len(stat) == 1
    assert stat[0].effects[0].params["affects"] == "creatures_opponents_control_with_a_counter"
    assert set(stat[0].effects[0].params["keywords"]) == {"cant_attack", "cant_block"}


def test_kulrath_knight_locks_down_only_countered_opponent_creatures():
    eng = _engine()
    st = eng.state
    kk = GameObject(KULRATH_KNIGHT, owner_id="p1", zone=Zone.BATTLEFIELD)
    kk.controller_id = "p1"
    st.add_to_battlefield(kk)
    bind_from_catalogue(kk)

    countered = GameObject(Card(id="C", name="Countered", type_line="Creature — Ogre",
                                is_creature=True, power=4, toughness=4),
                           owner_id="p2", zone=Zone.BATTLEFIELD)
    countered.controller_id = "p2"
    countered.counters["-1/-1"] = 1
    clean = GameObject(Card(id="K", name="Clean", type_line="Creature — Ox",
                            is_creature=True, power=2, toughness=2),
                       owner_id="p2", zone=Zone.BATTLEFIELD)
    clean.controller_id = "p2"
    mine_countered = GameObject(Card(id="M", name="MineC", type_line="Creature — Bear",
                                     is_creature=True, power=2, toughness=2),
                                owner_id="p1", zone=Zone.BATTLEFIELD)
    mine_countered.controller_id = "p1"
    mine_countered.counters["+1/+1"] = 1
    for o in (countered, clean, mine_countered):
        st.add_to_battlefield(o)

    eng.recompute_continuous_effects()

    # opponent's creature with a counter — locked
    assert combat.has(countered, "cant_attack")
    assert combat.has(countered, "cant_block")
    # opponent's creature with no counter — free
    assert not combat.has(clean, "cant_attack")
    assert not combat.has(clean, "cant_block")
    # my own countered creature — unaffected (opponents only)
    assert not combat.has(mine_countered, "cant_attack")
    assert not combat.has(mine_countered, "cant_block")


def test_kulrath_knight_lock_lifts_when_counter_removed():
    eng = _engine()
    st = eng.state
    kk = GameObject(KULRATH_KNIGHT, owner_id="p1", zone=Zone.BATTLEFIELD)
    kk.controller_id = "p1"
    st.add_to_battlefield(kk)
    bind_from_catalogue(kk)

    opp = GameObject(Card(id="O", name="Opp", type_line="Creature — Ogre",
                          is_creature=True, power=4, toughness=4),
                     owner_id="p2", zone=Zone.BATTLEFIELD)
    opp.controller_id = "p2"
    opp.counters["-1/-1"] = 2
    st.add_to_battlefield(opp)

    eng.recompute_continuous_effects()
    assert combat.has(opp, "cant_attack")

    opp.counters.pop("-1/-1")
    eng.recompute_continuous_effects()
    assert not combat.has(opp, "cant_attack")


def test_kulrath_knight_real_card_is_authored_modeled():
    from mtg_analyzer.game.ability_catalogue import specs_for as _sf
    assert _sf(KULRATH_KNIGHT)  # non-empty → AUTHORED
