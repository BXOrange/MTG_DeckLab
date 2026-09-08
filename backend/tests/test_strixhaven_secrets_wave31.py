"""Secrets of Strixhaven — playability batch, wave 31 (PAR-60).

Mixed singletons on small new primitives, hand-authored in
`game/ability_catalogue/entries_019.py`:
- `_mass_wipe_objects` ``enchanted`` filter (Winds of Rath)
- `cost_reduction_for` ``reduce_if_targets`` for battlefield statics (Killian)
- `continuous.count_selector` ``total_power_creatures_you_control`` (Volcanic Salvo)
- `DealDamageEffect` selector ``each_creature_and_planeswalker_opponents_control``
- binder predicate ``entering_mana_value_at_most`` (Tocasia's Welcome)
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.spec import EffectSpec

WAVE31 = ["Winds of Rath", "The Goose Mother", "Killian, Ink Duelist",
          "Volcanic Salvo", "Volcanic Torrent", "Tocasia's Welcome"]


@pytest.mark.parametrize("name", WAVE31)
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
    p1 = eng.state.active_player
    p2 = [p for p in eng.state.players if p.id != p1.id][0]
    return eng, p1, p2


def _mk(eng, pid, name, tl, **kw):
    o = GameObject(card=Card(id=name.replace(" ", ""), name=name, type_line=tl, **kw),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    eng.state.add_to_battlefield(o)
    return o


def test_winds_of_rath_spares_enchanted_creatures():
    eng, p1, p2 = _eng()
    bare = _mk(eng, p1.id, "Bare", "Creature — Bear", is_creature=True, power=2, toughness=2)
    holy = _mk(eng, p2.id, "Holy", "Creature — Angel", is_creature=True, power=3, toughness=3)
    aura = _mk(eng, p2.id, "Pacifism", "Enchantment — Aura")
    aura.attached_to = holy.instance_id
    effs = build_effects(_REGISTRY["winds of rath"]()[0].effects, bare)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    eng.rules.check_state_based_actions()  # resolve destroy
    names = {o.card.name for o in eng.state.battlefield}
    assert "Bare" not in names
    assert "Holy" in names


def test_volcanic_salvo_reduces_by_total_power():
    from mtg_analyzer.game.continuous import self_cost_reduction_for
    eng, p1, p2 = _eng()
    for i, p in enumerate((4, 5)):
        c = _mk(eng, p1.id, f"C{i}", "Creature — Ox", is_creature=True, power=p, toughness=p)
    salvo = GameObject(card=Card(id="vs", name="Volcanic Salvo", type_line="Sorcery"),
                       owner_id=p1.id, zone=Zone.HAND)
    salvo.controller_id = p1.id
    statics = [e for spec in _REGISTRY["volcanic salvo"]()
               if spec.ability_kind == "static" for e in spec.effects]
    salvo.static_effects.extend(build_effects(statics, salvo))
    eng.recompute_continuous_effects()
    net, _ = self_cost_reduction_for(salvo, eng.state, p1.id)
    assert net == 9


def test_volcanic_torrent_hits_opponent_creatures_and_planeswalkers():
    eng, p1, p2 = _eng()
    eng.state.spells_cast_this_turn[p1.id] = 3
    my_c = _mk(eng, p1.id, "Mine", "Creature — Bear", is_creature=True, power=5, toughness=5)
    opp_c = _mk(eng, p2.id, "Theirs", "Creature — Bear", is_creature=True, power=5, toughness=5)
    src = GameObject(card=Card(id="vt", name="Volcanic Torrent", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    effs = build_effects(_REGISTRY["volcanic torrent"]()[0].effects, src)
    ctx = GameContext(state=eng.state, engine=eng.rules)
    for e in effs:
        e.apply(ctx, [])
    assert opp_c.damage_marked == 3
    assert my_c.damage_marked == 0
