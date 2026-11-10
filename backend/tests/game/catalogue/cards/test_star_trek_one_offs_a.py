"""Star Trek (TRK/TRC) one-off cards, batch A: real cached cards on a real engine."""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.card_registry import specs_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card
from tests.support.star_trek import attack, cast, game, on_battlefield, stock_library, vanilla


def _into_hand(player, name, **card_kwargs):
    obj = GameObject(Card(id=name, name=name, **card_kwargs), owner_id=player.id, zone=Zone.HAND)
    player.add_to_zone(obj, Zone.HAND)
    return obj


def test_all_registered_and_fresh():
    for name in ("Ensign Harry Kim, Operations", "Khan, Despot by Design", "Year of Hell",
                 "Geordi La Forge, Innovator", "K'Vort-Class Raider", "Red Alert!", "Glory to the Empire!"):
        card = get_cached_card(name)
        first, second = specs_for(card), specs_for(card)
        assert first and first[0] is not second[0], name


def test_kim_grows_only_when_the_entrant_is_stronger_and_yours():
    engine, p1, p2 = game()
    kim = on_battlefield(engine, "p1", "Ensign Harry Kim, Operations")
    assert kim.power == 1
    small = _into_hand(p1, "Small", type_line="Creature — Bear", is_creature=True, power=1, toughness=1)
    cast(engine, p1, small)
    assert kim.counters.get("+1/+1", 0) == 0  # equal power: no trigger
    big = _into_hand(p1, "Big", type_line="Creature — Bear", is_creature=True, power=4, toughness=1)
    cast(engine, p1, big)
    assert kim.counters.get("+1/+1", 0) == 1
    # toughness alone does not count (unlike Evolve)
    tough = _into_hand(p1, "Tough", type_line="Creature — Bear", is_creature=True, power=1, toughness=9)
    cast(engine, p1, tough)
    assert kim.counters.get("+1/+1", 0) == 1


def test_kim_draws_by_removing_two_counters():
    engine, p1, p2 = game()
    kim = on_battlefield(engine, "p1", "Ensign Harry Kim, Operations")
    stock_library(engine, "p1", 3)
    kim.counters["+1/+1"] = 2
    p1.mana_pool.add_many({"C": 2})
    hand = len(p1.hand)
    engine.activate_ability(p1, kim)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 1 and kim.counters.get("+1/+1", 0) == 0


def test_khan_hits_each_opponent_and_each_opposing_creature_only():
    engine, p1, p2 = game("Khan, Despot by Design")
    mine = vanilla(engine, "p1", "Mine", 2, 2)
    their_small = vanilla(engine, "p2", "Their Small", 1, 1)
    their_big = vanilla(engine, "p2", "Their Big", 3, 3)
    cast(engine, p1, p1.hand[0])
    assert p2.life == 19 and p1.life == 20
    assert their_small not in engine.state.battlefield
    assert their_big.damage_marked == 1 and mine.damage_marked == 0


def test_year_of_hell_each_chapter_draws_and_pings_every_player():
    engine, p1, p2 = game("Year of Hell")
    stock_library(engine, "p1", 4)
    stock_library(engine, "p2", 4)
    cast(engine, p1, p1.hand[0])
    saga = next(o for o in engine.state.battlefield if o.name == "Year of Hell")
    assert saga.counters.get("lore", 0) == 1
    assert (p1.life, p2.life) == (18, 18)
    assert len(p1.hand) == 1 and len(p2.hand) == 1


def test_geordi_is_unblockable_only_with_a_spacecraft():
    engine, p1, p2 = game()
    geordi = on_battlefield(engine, "p1", "Geordi La Forge, Innovator")
    assert "cant_be_blocked" not in geordi.granted_keywords
    on_battlefield(engine, "p1", "K'Vort-Class Raider")
    engine.recompute_continuous_effects()
    assert "cant_be_blocked" in geordi.granted_keywords
    # an opposing Spacecraft does not count
    engine2, q1, q2 = game()
    geordi2 = on_battlefield(engine2, "p1", "Geordi La Forge, Innovator")
    on_battlefield(engine2, "p2", "K'Vort-Class Raider")
    engine2.recompute_continuous_effects()
    assert "cant_be_blocked" not in geordi2.granted_keywords


def test_geordi_draws_on_combat_damage_to_a_player():
    engine, p1, p2 = game(via_steps=True)
    geordi = on_battlefield(engine, "p1", "Geordi La Forge, Innovator")
    hand = len(p1.hand)
    attack(engine, p1, geordi)
    assert p2.life == 20 - geordi.power
    assert len(p1.hand) == hand + 1


def test_kvort_hexproof_only_on_your_turn_for_itself_and_your_creatures():
    engine, p1, p2 = game()
    raider = on_battlefield(engine, "p1", "K'Vort-Class Raider")
    mine = vanilla(engine, "p1", "Mine")
    theirs = vanilla(engine, "p2", "Theirs")
    engine.recompute_continuous_effects()
    assert engine.state.active_player.id == "p1"
    assert "hexproof" in raider.granted_keywords and "hexproof" in mine.granted_keywords
    assert "hexproof" not in theirs.granted_keywords
    engine.state.active_player_index = 1  # RULE 604.2: the grant lapses on the opponent's turn
    engine.recompute_continuous_effects()
    assert "hexproof" not in raider.granted_keywords and "hexproof" not in mine.granted_keywords


def test_kvort_is_a_creature_with_flying_menace_haste_at_four_charge_counters():
    engine, p1, p2 = game()
    raider = on_battlefield(engine, "p1", "K'Vort-Class Raider")
    assert not raider.is_creature
    raider.counters["charge"] = 4
    engine.recompute_continuous_effects()
    assert raider.is_creature
    assert {"flying", "menace", "haste"} <= set(raider.granted_keywords)


def test_red_alert_costs_two_less_only_while_a_creature_attacks_you():
    engine, p1, p2 = game("Red Alert!")
    spell = p1.hand[0]
    assert continuous.self_cost_reduction_for(spell, engine.state, "p1", [])[0] == 0
    attacker = vanilla(engine, "p2", "Attacker")
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": "p1"}
    assert continuous.self_cost_reduction_for(spell, engine.state, "p1", [])[0] == 2
    attacker.combat_defender = {"kind": "player", "id": "p2"}
    assert continuous.self_cost_reduction_for(spell, engine.state, "p1", [])[0] == 0


def test_red_alert_pumps_only_my_creatures():
    engine, p1, p2 = game("Red Alert!")
    mine = vanilla(engine, "p1", "Mine", 2, 2)
    theirs = vanilla(engine, "p2", "Theirs", 2, 2)
    cast(engine, p1, p1.hand[0])
    assert mine.power == 4 and theirs.power == 2


def test_glory_to_the_empire_makes_one_hasty_warrior_per_opponent_and_grants_melee():
    engine, p1, p2 = game("Glory to the Empire!")
    cast(engine, p1, p1.hand[0])
    tokens = [o for o in engine.state.battlefield if o.is_token]
    assert len(tokens) == 1
    token = tokens[0]
    assert (token.power, token.toughness) == (2, 1) and combat.has(token, "haste")
    assert "Klingon" in token.card.type_line and "Warrior" in token.card.type_line
    assert "melee" in token.granted_keywords
