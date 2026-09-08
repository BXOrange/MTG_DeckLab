"""Secrets of Strixhaven — playability batch, wave 23 (PAR-60).

Witherbloom "Pestilence": the "life you gained this turn" + sacrifice-matters
cluster, hand-authored in `game/ability_catalogue/entries_019.py`. New engine
primitives: the ``gained_life_this_turn`` `static_conditions` kind and the
``life_gained_this_turn`` `continuous.count_selector`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability, build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WAVE23 = [
    "Mortality Spear", "Defiling Daemogoth", "Witch of the Moors",
    "Blossoming Bogbeast", "Eccentric Pestfinder", "Merchant of Venom",
    "Mazirek, Kraul Death Priest", "Smothering Abomination",
    "Dina, Soul Steeper", "Dina, Essence Brewer",
]


@pytest.mark.parametrize("name", WAVE23)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(card=Card(id="x", name=name, type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def _eng():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    return eng, eng.state.active_player, [p for p in eng.state.players
                                         if p.id != eng.state.active_player.id][0]


def _mk(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", "").replace(",", ""), name=name,
                             type_line=tl, **kw), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_gained_life_this_turn_condition_and_selector():
    from mtg_analyzer.game import static_conditions
    from mtg_analyzer.game.continuous import count_selector
    eng, p1, p2 = _eng()
    cond = {"kind": "gained_life_this_turn"}
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is False
    assert count_selector(eng.state, p1.id, "life_gained_this_turn") == 0
    eng.rules.gain_life(p1, 3)
    assert static_conditions.condition_holds(cond, eng.state, None, p1.id) is True
    assert count_selector(eng.state, p1.id, "life_gained_this_turn") == 3


def test_blossoming_bogbeast_pumps_by_life_gained():
    eng, p1, p2 = _eng()
    bog = _mk(eng, p1.id, "Blossoming Bogbeast", "Creature — Beast",
              is_creature=True, power=4, toughness=4)
    other = _mk(eng, p1.id, "Buddy", "Creature — Bear", is_creature=True,
                power=2, toughness=2)
    effs = build_effects(_REGISTRY["blossoming bogbeast"]()[0].effects, bog)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    eng.recompute_continuous_effects()
    # gained 2 life this trigger -> +2/+2 and trample on all your creatures
    assert p1.life == 22
    assert (bog.power, bog.toughness) == (6, 6)
    assert (other.power, other.toughness) == (4, 4)
    assert "trample" in other.granted_keywords


def test_dina_soul_steeper_pump_reads_sacrificed_power():
    eng, p1, p2 = _eng()
    dina = _mk(eng, p1.id, "Dina, Soul Steeper", "Legendary Creature — Dryad Druid",
               is_creature=True, power=1, toughness=3)
    dina.sacrificed_cost_power = 5  # what the activation cost payment would stamp
    pump = build_effects([EffectSpec("pump", {
        "power": 0, "toughness": 0,
        "amount_from_count_selector": "sacrificed_cost_power",
        "amount_from_count_selector_axis": "power"})], dina)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in pump:
        e.apply(ctx, [])
    eng.recompute_continuous_effects()
    assert (dina.power, dina.toughness) == (6, 3)


def test_mortality_spear_discount_only_after_lifegain():
    from mtg_analyzer.game.continuous import self_cost_reduction_for
    eng, p1, p2 = _eng()
    spear = GameObject(card=Card(id="ms", name="Mortality Spear", type_line="Instant"),
                       owner_id=p1.id, zone=Zone.HAND)
    spear.controller_id = p1.id
    static_specs = [e for spec in _REGISTRY["mortality spear"]()
                    if spec.ability_kind == "static" for e in spec.effects]
    spear.static_effects.extend(build_effects(static_specs, spear))
    net, _ = self_cost_reduction_for(spear, eng.state, p1.id)
    assert net == 0
    eng.rules.gain_life(p1, 1)
    net, _ = self_cost_reduction_for(spear, eng.state, p1.id)
    assert net == 2
