"""Nils, Discipline Enforcer adds counters and taxes countered attackers."""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _nils_card():
    return Card(id="nils", name="Nils, Discipline Enforcer",
                type_line="Legendary Creature — Human Cleric", is_creature=True,
                power=2, toughness=4,
                oracle_text=("At the beginning of your end step, for each player, put a "
                             "+1/+1 counter on up to one target creature that player "
                             "controls.\nEach creature with one or more counters on it "
                             "can't attack you or planeswalkers you control unless its "
                             "controller pays {X}, where X is the number of counters on "
                             "that creature."))


def test_registered_and_binds():
    assert is_registered("Nils, Discipline Enforcer")
    specs = _REGISTRY["nils, discipline enforcer"]()
    assert [s.effects[0].type for s in specs] == ["nils_end_step_counters", "attack_tax"]
    src = GameObject(_nils_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_nils_card())


def test_end_step_counters_hit_each_players_best_creature():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    src = GameObject(_nils_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    mine_big = GameObject(Card(id="mb", name="MyBig", type_line="Creature", is_creature=True,
                               power=5, toughness=5), owner_id="p1", zone=Zone.BATTLEFIELD)
    mine_big.controller_id = "p1"
    mine_small = GameObject(Card(id="ms", name="MySmall", type_line="Creature",
                                 is_creature=True, power=1, toughness=1),
                            owner_id="p1", zone=Zone.BATTLEFIELD)
    mine_small.controller_id = "p1"
    theirs = GameObject(Card(id="tb", name="TheirBig", type_line="Creature", is_creature=True,
                             power=4, toughness=4), owner_id="p2", zone=Zone.BATTLEFIELD)
    theirs.controller_id = "p2"
    for o in (mine_big, mine_small, theirs):
        eng.state.add_to_battlefield(o)

    eng.rules._apply_effect_specs([{"type": "nils_end_step_counters", "params": {}}], src)
    assert mine_big.counters.get("+1/+1", 0) == 1
    assert mine_small.counters.get("+1/+1", 0) == 0
    assert theirs.counters.get("+1/+1", 0) == 1


def test_attack_tax_is_that_attackers_own_counter_count():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p2 = eng.state.player_by_id("p2")
    static = EffectRegistry.create("attack_tax", {
        "attacker_filter": {"has_any_counter": True},
        "amount_per_attacker_counter": "any",
        "defender_scope": "player_or_planeswalker",
    })
    holder = GameObject(_nils_card(), owner_id="p2", zone=Zone.BATTLEFIELD)
    holder.controller_id = "p2"
    static.source = holder
    holder.static_effects.append(static)
    eng.state.add_to_battlefield(holder)

    loaded = GameObject(Card(id="lo", name="Loaded", type_line="Creature", is_creature=True,
                             power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    loaded.controller_id = "p1"
    loaded.counters["+1/+1"] = 3
    plain = GameObject(Card(id="pl", name="Plain", type_line="Creature", is_creature=True,
                            power=1, toughness=1), owner_id="p1", zone=Zone.BATTLEFIELD)
    plain.controller_id = "p1"
    for o in (loaded, plain):
        eng.state.add_to_battlefield(o)

    assert continuous.attack_tax_per_creature_for(eng.state, "p2", "player", attacker=loaded) == 3
    assert continuous.attack_tax_per_creature_for(eng.state, "p2", "player", attacker=plain) == 0
