"""Regression tests for graveyard permissions and independently triggered payoffs."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import answer, attack, card, filler, game, main_phase, named, pick_label, step


@pytest.mark.parametrize("discard_method", ["discard", "discard_specific", "discard_random"])
def test_chameleon_mayhem_uses_its_alternative_cost_only_after_discard(discard_method):
    engine = game()
    me = engine.state.player_by_id("p1")
    chameleon = card(engine, "Chameleon, Master of Disguise", zone=Zone.HAND)
    me.mana_pool.add_many({"C": 2, "U": 1})
    main_phase(engine)
    assert not engine.can_cast(me, chameleon)
    if discard_method == "discard_specific":
        engine.rules.discard_specific(chameleon)
    else:
        getattr(engine.rules, discard_method)(me)
    assert engine.can_cast(me, chameleon)
    action = next(a for a in engine.legal_actions(me)
                  if a.get("instance_id") == chameleon.instance_id and a["type"] == "cast_spell")
    assert action["cast_from_graveyard"] == "mayhem"
    engine.cast_spell(me, chameleon)
    engine.resolve_until_stable()
    answer(engine, pick_label("Nein"))
    assert chameleon.zone == Zone.BATTLEFIELD and me.mana_pool.total() == 0


def test_mayhem_preserves_normal_timing_and_expires_after_the_discard_turn():
    engine = game()
    me = engine.state.player_by_id("p1")
    chameleon = card(engine, "Chameleon, Master of Disguise", zone=Zone.HAND)
    engine.rules.discard_specific(chameleon)
    me.mana_pool.add_many({"C": 2, "U": 1})
    engine.state.current_step = "begin_combat"
    assert not engine.can_cast(me, chameleon)
    main_phase(engine)
    assert engine.can_cast(me, chameleon)
    engine.state.internal_turn.number += 1
    assert not engine.can_cast(me, chameleon)


def test_mayhem_does_not_apply_to_a_milled_card_or_a_new_graveyard_incarnation():
    engine = game()
    me = engine.state.player_by_id("p1")
    chameleon = card(engine, "Chameleon, Master of Disguise", zone=Zone.GRAVEYARD)
    me.mana_pool.add_many({"C": 2, "U": 1})
    main_phase(engine)
    assert not engine.can_cast(me, chameleon)
    me.remove_from_zone(chameleon, Zone.GRAVEYARD)
    me.add_to_zone(chameleon, Zone.HAND)
    engine.rules.discard_specific(chameleon)
    assert engine.can_cast(me, chameleon)
    engine.rules.exile(chameleon)
    me.remove_from_zone(chameleon, Zone.EXILE)
    chameleon.reset_as_new_object()
    me.add_to_zone(chameleon, Zone.GRAVEYARD)
    assert not engine.can_cast(me, chameleon)


def test_costless_mayhem_permits_a_discarded_land_with_ordinary_land_limits():
    engine = game()
    me = engine.state.player_by_id("p1")
    land = filler(engine, "Mayhem Land", type_line="Land", zone=Zone.HAND,
                  oracle_text="Mayhem", keywords=["Mayhem"])
    engine.rules.discard_specific(land)
    main_phase(engine)
    assert engine.can_play_land(me, land)
    me.lands_played_this_turn = me.max_lands_per_turn
    assert not engine.can_play_land(me, land)


def test_yedora_forest_can_turn_face_up_using_its_printed_morph_cost():
    engine = game()
    card(engine, "Yedora, Grave Gardener")
    morph = card(engine, "Den Protector")
    engine.rules.destroy(morph)
    engine.resolve_until_stable()
    answer(engine, pick_label("Ja"))
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 1, "G": 1})
    assert morph.face_down and morph.is_land
    assert engine.turn_face_up_actions(me, morph)
    engine.turn_face_up(me, morph)
    assert not morph.face_down and morph.is_creature and morph.counters["+1/+1"] == 1


def test_thancred_protection_ends_permanently_when_control_is_lost():
    engine = game()
    thancred = card(engine, "Thancred Waters", zone=Zone.HAND)
    legend = filler(engine, "Legend", type_line="Legendary Creature", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    me.mana_pool.add_many({"C": 4, "W": 1})
    main_phase(engine)
    engine.cast_spell(me, thancred)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(legend.instance_id))
    assert combat.has(legend, "indestructible")
    thancred.controller_id = "p2"
    engine.recompute_continuous_effects()
    assert not combat.has(legend, "indestructible")
    thancred.controller_id = "p1"
    engine.recompute_continuous_effects()
    assert not combat.has(legend, "indestructible")


@pytest.mark.parametrize("departure", ["leave", "control"])
def test_colfenors_urn_does_not_return_cards_when_its_sacrifice_cannot_happen(departure):
    engine = game()
    urn = card(engine, "Colfenor's Urn")
    exiled = [filler(engine, f"Exiled {i}", power=2, toughness=4, zone=Zone.EXILE) for i in range(3)]
    urn.exiled_with_ids = [o.instance_id for o in exiled]
    engine.state.current_step = "end"
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end"))
    engine.rules.put_triggers_on_stack()
    assert engine.state.stack
    if departure == "leave":
        engine.rules.exile(urn)
    else:
        urn.controller_id = "p2"
    engine.resolve_until_stable()
    assert all(o.zone == Zone.EXILE for o in exiled)


@pytest.mark.parametrize("player,won,expected", [("p1", True, 2), ("p1", False, 0), ("p2", True, 0)])
def test_setzer_triggers_on_any_coin_its_controller_wins(player, won, expected, monkeypatch):
    engine = game()
    card(engine, "Setzer, Wandering Gambler")
    monkeypatch.setattr(engine.rules, "random_int", lambda maximum: 0 if won else 1)
    engine.rules.coin_flip(engine.state.player_by_id(player))
    engine.resolve_until_stable()
    treasures = named(engine, "Treasure")
    assert len(treasures) == expected and all(o.tapped for o in treasures)


def test_printed_mobilize_creates_attacking_warriors_and_sacrifices_them_at_next_end_step():
    engine = game()
    mobilizer = filler(engine, "Mobilizer", power=2, toughness=2,
                       oracle_text="Mobilize 2", keywords=["Mobilize"])
    attack(engine, [mobilizer])
    warriors = named(engine, "Warrior")
    assert len(warriors) == 2 and all(o.tapped and o.attacking for o in warriors)
    step(engine, "end")
    assert not named(engine, "Warrior") and mobilizer.zone == Zone.BATTLEFIELD


def test_aetherflux_casts_multiple_hand_spells_before_any_of_them_resolves():
    engine = game()
    conduit = card(engine, "Aetherflux Conduit")
    bolt = card(engine, "Lightning Bolt", zone=Zone.HAND)
    elf = card(engine, "Llanowar Elves", zone=Zone.HAND)
    me, enemy = engine.state.players
    me.counters["energy"] = 50
    main_phase(engine)
    engine.activate_ability(me, conduit, 0)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.play_resolution_card(me, bolt, targets=[enemy])
    assert enemy.life == 20 and bolt.zone == Zone.STACK
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.play_resolution_card(me, elf)
    engine.resolve_until_stable()
    assert enemy.life == 17 and elf.zone == Zone.BATTLEFIELD


def test_aetherflux_decline_expires_all_hand_permissions():
    engine = game()
    conduit = card(engine, "Aetherflux Conduit")
    spell = card(engine, "Llanowar Elves", zone=Zone.HAND)
    me = engine.state.player_by_id("p1")
    me.counters["energy"] = 50
    main_phase(engine)
    engine.activate_ability(me, conduit, 0)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")
    assert not engine.can_cast(me, spell)
    assert spell.instance_id not in engine.state.free_cast_instance_ids


def test_grenzo_exiles_a_land_without_granting_permission_to_play_it():
    engine = game()
    grenzo = card(engine, "Grenzo, Havoc Raiser")
    land = card(engine, "Forest", player="p2", zone=Zone.LIBRARY)
    attack(engine, [grenzo])
    engine._step_combat_damage()
    engine.resolve_until_stable()
    answer(engine, pick_label("Verbanne"))
    assert land.zone == Zone.EXILE
    main_phase(engine)
    assert not engine.can_play_land(engine.state.player_by_id("p1"), land)


def test_gix_decline_expires_the_exiled_cards_cast_permission():
    engine = game()
    gix = card(engine, "Gix, Yawgmoth Praetor")
    discard = filler(engine, "Discard", type_line="Instant", zone=Zone.HAND)
    spell = card(engine, "Llanowar Elves", player="p2", zone=Zone.LIBRARY)
    me, enemy = engine.state.players
    me.mana_pool.add_many({"C": 4, "B": 3})
    main_phase(engine)
    engine.activate_ability(me, gix, 0, targets=[enemy], x=1, discard_choices=[discard.instance_id])
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "play_during_resolution"
    engine.resolve_pending_choice("decline")
    assert spell.zone == Zone.EXILE and not engine.can_cast(me, spell)
