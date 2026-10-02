"""Hand-authored cards of the saved "Wick Snail Boom" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
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
    p1 = engine.state.player_by_id("p1")
    for i in range(5):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1


def _blink_spell(name, creature_type_line):
    engine, p1 = _game(name)
    creature = battlefield_object(engine, "p1", "Blinked", creature_type_line, is_creature=True, power=2, toughness=2)
    creature.counters["-1/-1"] = 1  # a counter proves the blink made a new object
    hand_before = len(p1.hand)
    p1.mana_pool.add_many({"U": 1, "C": p1.hand[0].card.converted_mana_cost - 1})
    engine.cast_spell(p1, p1.hand[0], targets=[creature])
    engine.resolve_until_stable()
    return engine, p1, creature, hand_before


def test_sirens_ruse_blinks_and_draws_only_for_a_pirate():
    engine, p1, creature, hand_before = _blink_spell("Siren's Ruse", "Creature — Human Pirate")
    assert creature in engine.state.battlefield and not creature.counters  # returned as a new object
    assert len(p1.hand) == hand_before - 1 + 1  # the spell leaves, one card is drawn

    engine, p1, creature, hand_before = _blink_spell("Siren's Ruse", "Creature — Human Wizard")
    assert creature in engine.state.battlefield
    assert len(p1.hand) == hand_before - 1  # no draw for a non-Pirate


def test_essence_flux_blinks_and_adds_a_counter_only_to_a_spirit():
    engine, p1, spirit, _ = _blink_spell("Essence Flux", "Creature — Spirit")
    assert spirit in engine.state.battlefield
    assert spirit.counters.get("+1/+1", 0) == 1 and not spirit.counters.get("-1/-1")

    engine, p1, human, _ = _blink_spell("Essence Flux", "Creature — Human")
    assert human in engine.state.battlefield and not human.counters


def _wings(name, my_type_line="Creature — Bear", on_opponents=False):
    engine, p1 = _game(name)
    controller = "p2" if on_opponents else "p1"
    target = battlefield_object(engine, controller, "Target", my_type_line, is_creature=True, power=1, toughness=1)
    target.counters["+1/+1"] = 1  # counters still apply on top of a base P/T
    other = battlefield_object(engine, "p1", "Other", "Creature — Bear", is_creature=True, power=1, toughness=1)
    p1.mana_pool.add_many({"U": 1, "C": p1.hand[0].card.converted_mana_cost - 1})
    engine.cast_spell(p1, p1.hand[0], targets=[target])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    return engine, target, other


def test_water_wings_sets_base_4_4_with_flying_and_hexproof_until_end_of_turn():
    engine, target, other = _wings("Water Wings")
    assert (target.power, target.toughness) == (5, 5)  # base 4/4 plus the +1/+1 counter
    assert {"flying", "hexproof"} <= set(target.granted_keywords)
    assert (other.power, other.toughness) == (1, 1)

    engine._step_cleanup()  # RULE 514.2: "until end of turn" effects end
    engine.recompute_continuous_effects()
    assert (target.power, target.toughness) == (2, 2) and "flying" not in target.granted_keywords


def test_wings_of_velis_vel_can_target_any_creature_and_grants_all_creature_types():
    engine, target, other = _wings("Wings of Velis Vel", on_opponents=True)
    assert (target.power, target.toughness) == (5, 5)
    assert "flying" in target.granted_keywords
    from mtg_analyzer.game.continuous import has_subtype

    assert has_subtype(target, "Elf") and has_subtype(target, "Wizard")  # every creature type
    assert not has_subtype(other, "Wizard")


def test_demonspine_whip_pumps_only_the_equipped_creature_by_the_paid_x():
    engine, p1 = _game()
    whip_card = CardDatabase(DB_PATH).get_card("Demonspine Whip")
    whip = GameObject(whip_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    whip.controller_id = "p1"
    bind_from_catalogue(whip)
    engine.state.add_to_battlefield(whip)
    host = battlefield_object(engine, "p1", "Host", "Creature — Bear", is_creature=True, power=2, toughness=2)
    bystander = battlefield_object(engine, "p1", "Bystander", "Creature — Bear", is_creature=True, power=2, toughness=2)
    whip.attached_to = host.instance_id
    engine.recompute_continuous_effects()

    index = next(i for i, a in enumerate(whip.activated_abilities) if getattr(a, "cost", None) is not None)
    p1.mana_pool.add_many({"C": 3})
    engine.activate_ability(p1, whip, index, x=3)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()

    assert (host.power, host.toughness) == (5, 2)  # +3/+0
    assert (bystander.power, bystander.toughness) == (2, 2)

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert host.power == 2  # until end of turn


def test_disciple_of_bolas_sacrifices_another_creature_and_gains_and_draws_its_power():
    engine, p1 = _game("Disciple of Bolas")
    fodder = battlefield_object(engine, "p1", "Fodder", "Creature — Ogre", is_creature=True, power=4, toughness=4)
    p1.mana_pool.add_many({"B": 1, "C": p1.hand[0].card.converted_mana_cost - 1})
    life_before, hand_before = p1.life, len(p1.hand)

    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()  # the creature spell, then its enters trigger
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    while engine.state.pending_choice:  # the forced sacrifice has exactly one candidate besides Disciple
        options = [o for o in engine.state.pending_choice["options"] if o["id"] != "decline"]
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_until_stable()

    assert fodder.zone != Zone.BATTLEFIELD  # sacrificed
    assert any(o.name == "Disciple of Bolas" for o in engine.state.battlefield)  # "another": it stays
    assert p1.life == life_before + 4
    assert len(p1.hand) == hand_before - 1 + 4  # the Disciple leaves the hand, four cards are drawn


def _big_apple(opponents):
    card = CardDatabase(DB_PATH).get_card("Big Apple, 3 a.m.")
    seats = [("p1", "A", [])] + [(f"p{i}", f"B{i}", []) for i in range(2, 2 + opponents)]
    engine = GameEngine.new_game(seats, starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    land = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    bind_from_catalogue(land)
    land.summoning_sick = False
    engine.state.add_to_battlefield(land)
    index = next(i for i, a in enumerate(land.activated_abilities) if getattr(a, "cost", None) is not None)
    p1.mana_pool.add_many({"C": 5})
    engine.activate_ability(p1, land, index)
    engine.resolve_until_stable()
    return [o for o in engine.state.permanents_controlled_by("p1") if "Rat" in (o.card.type_line or "")], land


def test_big_apple_makes_one_rat_per_opponent():
    rats, land = _big_apple(opponents=1)
    assert len(rats) == 1 and land.tapped
    assert (rats[0].power, rats[0].toughness) == (1, 1)

    rats, _ = _big_apple(opponents=3)
    assert len(rats) == 3  # a Commander pod: three opponents, three Rats


def _skitterspike_game(opponents=1):
    card = CardDatabase(DB_PATH).get_card("Giggling Skitterspike")
    seats = [("p1", "A", [])] + [(f"p{i}", f"B{i}", []) for i in range(2, 2 + opponents)]
    engine = GameEngine.new_game(seats, starting_hand=0, starting_life=20)
    engine.begin_turn()
    engine.state.current_step = "main1"
    spike = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    spike.controller_id = "p1"
    bind_from_catalogue(spike)
    spike.summoning_sick = False
    engine.state.add_to_battlefield(spike)
    engine.recompute_continuous_effects()
    return engine, spike


def test_giggling_skitterspike_hits_every_opponent_for_its_power_when_it_attacks():
    engine, spike = _skitterspike_game(opponents=2)
    power = spike.power
    assert power and power > 0
    engine.state.current_step = "declare_attackers"
    p1 = engine.state.player_by_id("p1")
    engine.declare_attackers(p1, [{"attacker": spike, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 20 - power
    assert engine.state.player_by_id("p3").life == 20 - power  # each opponent
    assert engine.state.player_by_id("p1").life == 20


def test_giggling_skitterspike_also_triggers_when_a_spell_targets_it():
    engine, spike = _skitterspike_game()
    p2 = engine.state.player_by_id("p2")
    bolt = GameObject(
        Card(id="Bolt", name="Opposing Bolt", type_line="Instant", is_instant=True, mana_cost_string="{R}", converted_mana_cost=1),
        owner_id="p2", zone=Zone.HAND,
    )
    bind_from_catalogue(bolt)
    p2.add_to_zone(bolt, Zone.HAND)
    p1 = engine.state.player_by_id("p1")
    life_before = p2.life
    engine.state.active_player_index = 1
    p2.mana_pool.add_many({"R": 1})
    engine.cast_spell(p2, bolt, targets=[spike])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert p2.life == life_before - spike.power  # the spike's controller's opponent is hit
