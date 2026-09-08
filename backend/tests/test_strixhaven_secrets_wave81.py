"""Secrets of Strixhaven — playability batch, wave 81 (PAR-60).

Forgotten Ancient — new `move_all_plus_one_counters_from_self` effect
(all +1/+1 counters onto one up-to-one target creature — documented
simplification of RULE 122 per-counter distribution).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _ancient_card():
    return Card(id="fa", name="Forgotten Ancient", type_line="Creature — Elemental",
                is_creature=True, power=0, toughness=3,
                oracle_text=("Whenever a player casts a spell, you may put a +1/+1 "
                             "counter on this creature.\nAt the beginning of your "
                             "upkeep, you may move any number of +1/+1 counters from "
                             "this creature onto other creatures."))


def test_registered_and_binds():
    assert is_registered("Forgotten Ancient")
    specs = _REGISTRY["forgotten ancient"]()
    assert len(specs) == 2
    assert specs[0].trigger["event"] == "SPELL_CAST"
    assert specs[1].effects[0].type == "move_all_plus_one_counters_from_self"
    src = GameObject(_ancient_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_ancient_card())


def test_moves_all_plus_one_counters_to_the_target():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    anc = GameObject(_ancient_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    anc.controller_id = "p1"
    eng.state.add_to_battlefield(anc)
    bind_from_catalogue(anc)
    anc.add_counters("+1/+1", 5)

    other = GameObject(Card(id="o", name="Other", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    eng.state.add_to_battlefield(other)
    eng.recompute_continuous_effects()

    eng.rules._apply_effect_specs(
        [{"type": "move_all_plus_one_counters_from_self", "params": {}}],
        anc, targets=[other],
    )
    eng.resolve_until_stable()
    assert anc.counters.get("+1/+1", 0) == 0
    assert other.counters.get("+1/+1") == 5
