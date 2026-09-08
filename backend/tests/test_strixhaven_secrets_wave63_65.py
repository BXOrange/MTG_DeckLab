"""Secrets of Strixhaven — playability batch, waves 63-65 (PAR-60).

wave 63: Gorma, the Gullet — ``extra_etb_counter`` static gained
         ``count_selector`` (live count) + a ``nontoken`` filter.
wave 64: Promise of Loyalty — pure reuse
         (``SacrificeEffect(selector="each_player", count="all_but_one")``).
wave 65: Songbirds' Blessing — pure reuse (``dig_until`` on an
         ``attached_permanent`` ATTACKS trigger).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def test_gorma_extra_etb_counters_scale_with_creatures_died_this_turn():
    assert is_registered("Gorma, the Gullet")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    g = GameObject(card=Card(id="g", name="Gorma, the Gullet",
                            type_line="Legendary Creature — Pest Frog", is_creature=True,
                            power=1, toughness=1),
                   owner_id=p1.id, zone=Zone.BATTLEFIELD)
    g.controller_id = p1.id
    eng.state.add_to_battlefield(g)
    bind_from_catalogue(g)
    eng.state.creatures_died_this_turn[p1.id] = 3

    nontoken = GameObject(card=Card(id="n", name="Newbie", type_line="Creature — Beast",
                                   is_creature=True, power=2, toughness=2),
                          owner_id=p1.id, zone=Zone.BATTLEFIELD)
    nontoken.controller_id = p1.id
    assert continuous.extra_etb_counters_for(eng.state, nontoken) == {"+1/+1": 3}

    token = GameObject(card=Card(id="t", name="Tok", type_line="Token Creature — Insect",
                                is_creature=True, power=1, toughness=1),
                       owner_id=p1.id, zone=Zone.BATTLEFIELD)
    token.controller_id = p1.id
    token.is_token = True
    assert continuous.extra_etb_counters_for(eng.state, token) == {}

    eng.state.creatures_died_this_turn[p1.id] = 0
    assert continuous.extra_etb_counters_for(eng.state, nontoken) == {}


def test_promise_of_loyalty_each_player_keeps_one_creature():
    assert is_registered("Promise of Loyalty")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    for pl, n in ((p1, 3), (p2, 2)):
        for i in range(n):
            o = GameObject(card=Card(id=f"{pl.id}{i}", name=f"{pl.id}{i}",
                                    type_line="Creature — Bear", is_creature=True,
                                    power=2, toughness=2),
                           owner_id=pl.id, zone=Zone.BATTLEFIELD)
            o.controller_id = pl.id
            eng.state.add_to_battlefield(o)
    src = GameObject(card=Card(id="pol", name="Promise of Loyalty", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    ability = bind_ability(_REGISTRY["promise of loyalty"]()[0], src)
    for e in (ability if isinstance(ability, list) else [ability]):
        e.source = src
        e.apply(eng.rules.context)
    # drain the interactive sacrifice chain (auto-pick) + deferred players
    for _ in range(20):
        pc = eng.state.pending_choice
        if pc and pc.get("kind") == "choose_objects":
            opts = [o for o in pc.get("options", []) if o.get("id") != "decline"]
            eng.rules.resolve_choose_objects_choice(
                opts[0]["instance_id"] if opts else None)
        else:
            break
    eng.rules.resume_deferred_effects()
    for _ in range(20):
        pc = eng.state.pending_choice
        if pc and pc.get("kind") == "choose_objects":
            opts = [o for o in pc.get("options", []) if o.get("id") != "decline"]
            eng.rules.resolve_choose_objects_choice(
                opts[0]["instance_id"] if opts else None)
        else:
            break
    eng.resolve_until_stable()

    assert len([o for o in eng.state.battlefield
                if o.controller_id == p1.id and o.is_creature]) == 1
    assert len([o for o in eng.state.battlefield
                if o.controller_id == p2.id and o.is_creature]) == 1


def test_songbirds_blessing_registered_and_binds():
    assert is_registered("Songbirds' Blessing")
    spec = _REGISTRY["songbirds' blessing"]()[0]
    spec.validate()
    assert spec.trigger["condition"]["subject"] == "attached_permanent"
    assert spec.effects[0].type == "dig_until"
    assert spec.effects[0].params["criteria"] == {"type": "Aura"}
    src = GameObject(card=Card(id="sb", name="Songbirds' Blessing",
                             type_line="Enchantment — Aura"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)
