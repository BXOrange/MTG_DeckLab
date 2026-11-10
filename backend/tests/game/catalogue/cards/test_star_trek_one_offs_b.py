"""Star Trek (TRK/TRC) one-off cards, batch B: real cached cards on a real engine."""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, cast, game, on_battlefield, stock_library, vanilla


def _into_graveyard(player, count):
    for i in range(count):
        obj = GameObject(Card(id=f"G{i}", name=f"Grave {i}", type_line="Land", is_land=True),
                         owner_id=player.id, zone=Zone.GRAVEYARD)
        player.graveyard.append(obj)


def test_de_evolve_shrinks_silences_and_retypes_the_creature():
    engine, p1, p2 = game("De-evolve")
    target = on_battlefield(engine, "p2", "Elvish Mystic")
    target.card.power, target.card.toughness = 5, 5
    engine.recompute_continuous_effects()
    cast(engine, p1, p1.hand[0], targets=[target])
    assert target.power == 1 and target.toughness == 5
    assert "cant_block" in target.granted_keywords
    subtypes = {t.lower() for t in target._derived_subtypes}
    assert subtypes == {"salamander"}  # RULE 205.3m: the old creature types are gone


def test_de_evolve_threshold_exiles_the_creature_at_upkeep():
    engine, p1, p2 = game("De-evolve", via_steps=True)
    target = vanilla(engine, "p2", "Victim", 3, 3)
    cast(engine, p1, p1.hand[0], targets=[target])
    _into_graveyard(p1, 6)
    advance_to(engine, "end")  # still our turn: the trigger is "each upkeep", none is begun
    engine.resolve_until_stable()
    assert target in engine.state.battlefield
    advance_to(engine, "upkeep")  # the opponent's upkeep, six cards: Threshold is off
    engine.resolve_until_stable()
    assert target in engine.state.battlefield
    _into_graveyard(p1, 1)
    advance_to(engine, "end")
    advance_to(engine, "upkeep")  # our next upkeep with seven cards in our graveyard
    engine.resolve_until_stable()
    assert target not in engine.state.battlefield


def test_dahar_master_sacrifices_a_nonland_permanent_then_shoots():
    engine, p1, p2 = game("Dahar Master")
    fodder = vanilla(engine, "p1", "Fodder")
    cast(engine, p1, p1.hand[0])
    assert engine.state.pending_choice["kind"] == "pay_cost_then"  # the optional sacrifice is offered
    engine.resolve_pending_choice("pay")
    engine.resolve_pending_choice("p2")  # the reflexive trigger's "any target"
    engine.resolve_until_stable()
    assert fodder not in engine.state.battlefield
    assert p2.life == 18


def test_enterprise_c_discards_hand_and_draws_that_many():
    engine, p1, p2 = game("U.S.S. Enterprise-C, Time-Tossed")
    stock_library(engine, "p1", 6)
    for name in ("A", "B", "C"):
        p1.add_to_zone(GameObject(Card(id=name, name=name, type_line="Land", is_land=True),
                                  owner_id="p1", zone=Zone.HAND), Zone.HAND)
    cast(engine, p1, p1.hand[0])
    assert engine.state.pending_choice["kind"] == "composite_optional"  # "you may discard your hand"
    engine.resolve_pending_choice("yes")
    engine.resolve_until_stable()
    assert len(p1.hand) == 3 and len(p1.graveyard) == 3  # discarded A, B, C, drew three


def test_enterprise_c_declining_keeps_the_hand():
    engine, p1, p2 = game("U.S.S. Enterprise-C, Time-Tossed")
    stock_library(engine, "p1", 6)
    p1.add_to_zone(GameObject(Card(id="A", name="A", type_line="Land", is_land=True),
                              owner_id="p1", zone=Zone.HAND), Zone.HAND)
    cast(engine, p1, p1.hand[0])
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert len(p1.hand) == 1 and not p1.graveyard


def test_beckett_promotes_on_the_third_tap_and_burns_each_opponent():
    engine, p1, p2 = game()
    beckett = on_battlefield(engine, "p1", "Beckett Mariner, Impetuous Ensign")
    for expected in (1, 2):
        engine.rules.set_tapped(beckett, True)
        engine.resolve_until_stable()
        assert beckett.counters.get("promotion", 0) == expected and p2.life == 20
        beckett.tapped = False
    engine.rules.set_tapped(beckett, True)
    engine.resolve_until_stable()
    assert beckett.counters.get("promotion", 0) == 0 and p2.life == 18


def test_kes_grows_draws_x_and_sacrifices_at_nine_counters():
    engine, p1, p2 = game(via_steps=True)
    kes = on_battlefield(engine, "p1", "Kes, Evolving Telepath")
    kes.counters["time"] = 8
    stock_library(engine, "p1", 10)
    hand = len(p1.hand)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 9
    assert kes not in engine.state.battlefield


def test_jadzia_adds_green_mana_per_counter_at_first_main():
    engine, p1, p2 = game(via_steps=True, stop_at="draw")
    jadzia = on_battlefield(engine, "p1", "Jadzia Dax, Living Legacy")
    jadzia.counters["+1/+1"] = 1
    added = []  # the pool empties as the step ends, so record what the trigger produced
    original_add = p1.mana_pool.add
    p1.mana_pool.add = lambda *args, **kwargs: (added.append(args), original_add(*args, **kwargs))[1]
    advance_to(engine, "main1")
    engine.resolve_until_stable()
    assert jadzia.counters.get("+1/+1") == 2
    assert added == [("G", 2)]  # one {G} per counter, counted after the new counter


def test_merciful_mandate_untaps_and_may_end_combat():
    engine, p1, p2 = game("Merciful Mandate")
    mine = vanilla(engine, "p1", "Mine")
    mine.tapped = True
    cast(engine, p1, p1.hand[0])
    assert not mine.tapped


def test_merciful_mandate_offers_to_end_combat_only_during_a_combat_phase():
    engine, p1, p2 = game("Merciful Mandate", via_steps=True)
    attacker = vanilla(engine, "p1", "Attacker")
    cast(engine, p1, p1.hand[0])
    assert engine.state.pending_choice is None  # main phase: nothing to end

    engine, p1, p2 = game("Merciful Mandate", via_steps=True)
    attacker = vanilla(engine, "p1", "Attacker")
    advance_to(engine, "declare_attackers")
    engine.declare_attackers(p1, [{"attacker": attacker, "defender": engine.legal_defenders_for(p1)[0]}])
    assert attacker.attacking
    cast(engine, p1, p1.hand[0])
    assert engine.state.pending_choice["kind"] == "composite_optional"
    engine.resolve_pending_choice("yes")
    engine.resolve_until_stable()
    assert not attacker.attacking and not attacker.tapped  # removed from combat and untapped


def test_fevered_visions_draws_for_each_player_and_burns_only_full_handed_opponents():
    engine, p1, p2 = game("Fevered Visions", via_steps=True)
    cast(engine, p1, p1.hand[0])
    for pid in ("p1", "p2"):
        stock_library(engine, pid, 10)
    # our end step: we draw; we are not an opponent, so no damage whatever our hand size
    for _ in range(5):
        p1.add_to_zone(GameObject(Card(id=f"X{_}", name=f"X{_}", type_line="Land", is_land=True),
                                  owner_id="p1", zone=Zone.HAND), Zone.HAND)
    hand = len(p1.hand)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert len(p1.hand) == hand + 1 and p1.life == 20
    # the opponent's end step with three cards in hand: draws to four, takes 2
    for _ in range(3):
        p2.add_to_zone(GameObject(Card(id=f"Y{_}", name=f"Y{_}", type_line="Land", is_land=True),
                                  owner_id="p2", zone=Zone.HAND), Zone.HAND)
    advance_to(engine, "upkeep")
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert engine.state.active_player.id == "p2"
    assert p2.life == 18 and len(p2.hand) >= 4


def test_live_long_and_prosper_doubles_life_draws_hand_size_and_lifts_hand_limit():
    engine, p1, p2 = game("Live Long and Prosper")
    stock_library(engine, "p1", 10)
    for i in range(2):
        p1.add_to_zone(GameObject(Card(id=f"H{i}", name=f"H{i}", type_line="Land", is_land=True),
                                  owner_id="p1", zone=Zone.HAND), Zone.HAND)
    p1.life = 13
    cast(engine, p1, p1.hand[0])
    assert p1.life == 26
    assert len(p1.hand) == 4  # two cards in hand after casting, doubled
    assert continuous.has_no_maximum_hand_size(engine.state, p1)


def test_temporal_conqueror_returns_a_milled_land_else_makes_a_treasure():
    engine, p1, p2 = game("Temporal Conqueror")
    stock_library(engine, "p1", 5, type_line="Land")
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    assert any(o.card.is_land for o in p1.hand) and not any(o.name == "Treasure" for o in engine.state.battlefield)

    engine, p1, p2 = game("Temporal Conqueror")
    stock_library(engine, "p1", 5, type_line="Instant")
    cast(engine, p1, p1.hand[0])
    assert any(o.name == "Treasure" for o in engine.state.battlefield)
    assert not p1.hand
