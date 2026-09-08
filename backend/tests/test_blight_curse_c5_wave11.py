"""Blight Curse batch C5 wave 11 — Everlasting Torment
(hand-authored, `ability_catalogue/entries_017.py`).

Three standing battlefield statics:
* ``prevent_all_life_gain`` — "Players can't gain life." (already parser-claimed)
* ``damage_cant_be_prevented`` — new marker static, RULE 615, read by
  `RulesEngine._run_replacement_loop` via
  `continuous.damage_prevention_globally_disabled`.
* ``global_wither`` — new marker static, RULE 609.4b as-though, read by
  `RulesEngine.deal_damage` via `continuous.global_wither_active`.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


EVERLASTING_TORMENT = Card(
    id="EVT", name="Everlasting Torment", type_line="Enchantment",
    oracle_text="Players can't gain life.\nDamage can't be prevented.\nAll damage is "
                "dealt as though its source had wither.",
)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(cid, ctrl, **kw):
    c = Card(id=cid, name=cid, type_line="Creature — Ogre", is_creature=True,
             power=kw.get("power", 3), toughness=kw.get("toughness", 3))
    o = GameObject(c, owner_id=ctrl, zone=Zone.BATTLEFIELD)
    o.controller_id = ctrl
    return o


def _with_torment(eng):
    et = GameObject(EVERLASTING_TORMENT, owner_id="p1", zone=Zone.BATTLEFIELD)
    et.controller_id = "p1"
    eng.state.add_to_battlefield(et)
    bind_from_catalogue(et)
    eng.recompute_continuous_effects()
    return et


def test_everlasting_torment_authored_three_statics():
    types = [e.type for s in specs_for(EVERLASTING_TORMENT) for e in s.effects]
    assert types == ["prevent_all_life_gain", "damage_cant_be_prevented", "global_wither"]


def test_global_wither_recolours_a_plain_sources_damage_to_counters():
    eng = _engine()
    _with_torment(eng)
    src = _creature("S", "p1")          # no wither keyword
    tgt = _creature("T", "p2", toughness=5)
    eng.state.add_to_battlefield(src)
    eng.state.add_to_battlefield(tgt)

    eng.rules.deal_damage(tgt, 2, source=src)

    assert tgt.counters.get("-1/-1", 0) == 2
    assert getattr(tgt, "damage_marked", 0) == 0


def test_global_wither_inactive_once_torment_leaves():
    eng = _engine()
    et = _with_torment(eng)
    src = _creature("S", "p1")
    tgt = _creature("T", "p2", toughness=5)
    eng.state.add_to_battlefield(src)
    eng.state.add_to_battlefield(tgt)

    eng.state.battlefield.remove(et)
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(tgt, 2, source=src)

    assert tgt.counters.get("-1/-1", 0) == 0
    assert getattr(tgt, "damage_marked", 0) == 2


def test_damage_cant_be_prevented_makes_a_shield_inert():
    eng = _engine()
    _with_torment(eng)
    src = _creature("S", "p1")
    tgt = _creature("T", "p2", toughness=9)
    eng.state.add_to_battlefield(src)
    eng.state.add_to_battlefield(tgt)

    eng.rules.prevent_damage_to_target(tgt, "all")
    eng.rules.deal_damage(tgt, 4, source=src)

    # prevention shield ignored -> the 4 still lands (as -1/-1 counters,
    # since global wither is also active)
    assert tgt.counters.get("-1/-1", 0) == 4


def test_players_cant_gain_life_under_torment():
    eng = _engine()
    _with_torment(eng)
    p2 = eng.state.players[1]
    start = p2.life
    eng.rules.gain_life(p2, 5)
    assert p2.life == start
