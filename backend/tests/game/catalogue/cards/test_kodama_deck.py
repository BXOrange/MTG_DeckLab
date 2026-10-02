"""Hand-authored cards of the saved "Kodama" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def _game(*deck_names):
    cards = [CardDatabase(DB_PATH).get_card(name) for name in deck_names]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=len(cards), starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state.player_by_id("p1"), engine.state.player_by_id("p2")


def test_titanic_brawl_costs_one_less_only_when_it_targets_my_creature_with_a_counter():
    engine, p1, p2 = _game("Titanic Brawl")
    spell = p1.hand[0]
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    grown = battlefield_object(engine, "p1", "Grown Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    grown.counters["+1/+1"] = 1
    victim = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    victim.counters["+1/+1"] = 1  # an opposing counter must not count

    def discount(*targets):
        return continuous.self_cost_reduction_for(spell, engine.state, "p1", list(targets))[0]

    assert discount(grown, victim) == 1
    assert discount(plain, victim) == 0
    assert discount(victim) == 0


def test_titanic_brawl_is_castable_for_the_reduced_cost_and_fights():
    engine, p1, p2 = _game("Titanic Brawl")
    spell = p1.hand[0]
    grown = battlefield_object(engine, "p1", "Grown Bear", "Creature — Bear", is_creature=True, power=3, toughness=3)
    grown.counters["+1/+1"] = 1
    victim = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    full_cost = spell.card.converted_mana_cost
    p1.mana_pool.add_many({"G": 1, "C": full_cost - 2})  # one less than printed

    engine.cast_spell(p1, spell, targets=[grown, victim])
    engine.resolve_until_stable()
    assert victim not in engine.state.battlefield  # 3 damage from the grown bear
    assert grown.damage_marked == 2  # the victim's power comes back


def test_inspiring_call_draws_per_countered_creature_and_makes_only_those_indestructible():
    engine, p1, p2 = _game("Inspiring Call")
    spell = p1.hand[0]
    grown = [
        battlefield_object(engine, "p1", f"Grown {i}", "Creature — Bear", is_creature=True, power=2, toughness=2)
        for i in range(2)
    ]
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    for creature in (*grown, theirs):
        creature.counters["+1/+1"] = 1
    for i in range(4):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    engine.recompute_continuous_effects()

    p1.mana_pool.add_many({"G": 1, "C": spell.card.converted_mana_cost - 1})
    hand_before = len(p1.hand)
    engine.cast_spell(p1, spell)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert len(p1.hand) == hand_before - 1 + 2  # the spell leaves, two creatures had a counter
    assert all("indestructible" in c.granted_keywords for c in grown)
    assert "indestructible" not in plain.granted_keywords
    assert "indestructible" not in theirs.granted_keywords


def test_pathbreaker_ibex_pumps_every_creature_by_the_greatest_power_and_gives_trample():
    engine, p1, p2 = _game()
    player = engine.state.active_player
    ibex = battlefield_object(engine, "p1", "Pathbreaker Ibex", "Creature — Goat", is_creature=True, power=3, toughness=3)
    bind_from_catalogue(ibex)
    big = battlefield_object(engine, "p1", "Big Bear", "Creature — Bear", is_creature=True, power=5, toughness=5)
    small = battlefield_object(engine, "p1", "Small Bear", "Creature — Bear", is_creature=True, power=1, toughness=1)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    for creature in (ibex, big, small):
        creature.summoning_sick = False
    engine.recompute_continuous_effects()

    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(player, [ibex])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert (big.power, big.toughness) == (10, 10)  # +5/+5: X is read once, before any bonus
    assert (small.power, small.toughness) == (6, 6)
    assert (ibex.power, ibex.toughness) == (8, 8)
    assert (theirs.power, theirs.toughness) == (2, 2)
    assert all("trample" in c.granted_keywords for c in (ibex, big, small))
    assert "trample" not in theirs.granted_keywords


def test_sapling_nursery_exiles_itself_to_make_treefolk_and_forests_indestructible():
    engine, p1, p2 = _game()
    card = CardDatabase(DB_PATH).get_card("Sapling Nursery")
    nursery = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    nursery.controller_id = "p1"
    bind_from_catalogue(nursery)
    engine.state.add_to_battlefield(nursery)
    treefolk = battlefield_object(engine, "p1", "Treefolk Token", "Creature — Treefolk", is_creature=True, power=3, toughness=4)
    forest = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    island = battlefield_object(engine, "p1", "Island", "Basic Land — Island", is_land=True)
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Forest", "Basic Land — Forest", is_land=True)
    p1.mana_pool.add_many({"G": 1, "C": 1})

    index = next(i for i, a in enumerate(nursery.activated_abilities) if getattr(a, "cost", None) is not None)
    engine.activate_ability(p1, nursery, index)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert nursery not in engine.state.battlefield  # exiled as the cost
    assert "indestructible" in treefolk.granted_keywords and "indestructible" in forest.granted_keywords
    assert "indestructible" not in island.granted_keywords
    assert "indestructible" not in bear.granted_keywords
    assert "indestructible" not in theirs.granted_keywords  # only mine


def test_sapling_nursery_keeps_affinity_for_forests_after_being_registered():
    engine, p1, p2 = _game("Sapling Nursery")
    spell = p1.hand[0]
    battlefield_object(engine, "p1", "Forest A", "Basic Land — Forest", is_land=True)
    battlefield_object(engine, "p1", "Forest B", "Basic Land — Forest", is_land=True)
    battlefield_object(engine, "p1", "Island", "Basic Land — Island", is_land=True)
    assert continuous.self_cost_reduction_for(spell, engine.state, "p1")[0] == 2  # one per Forest, not per land
