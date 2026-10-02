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
