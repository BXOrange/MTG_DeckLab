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
