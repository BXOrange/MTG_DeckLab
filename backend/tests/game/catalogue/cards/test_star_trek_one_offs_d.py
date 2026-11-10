"""Star Trek (TRK/TRC) one-off cards, batch D: real cached cards on a real engine."""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.star_trek import advance_to, attack, cast, game, on_battlefield, stock_library, vanilla


def test_khaaan_deals_twice_x_and_exiles_what_it_kills():
    engine, p1, p2 = game("Khaaaaaaaaaaaannn!")
    victim = vanilla(engine, "p2", "Victim", 3, 3)
    cast(engine, p1, p1.hand[0], targets=[victim], x=2)
    assert victim not in engine.state.battlefield
    assert victim in p2.exile and victim not in p2.graveyard  # RULE 614.1a: exiled, not dead


def test_khaaan_x_one_only_marks_two_damage():
    engine, p1, p2 = game("Khaaaaaaaaaaaannn!")
    victim = vanilla(engine, "p2", "Tough", 5, 5)
    cast(engine, p1, p1.hand[0], targets=[victim], x=1)
    assert victim in engine.state.battlefield and victim.damage_marked == 2


def test_prometheus_levels_flying_creature_and_multivector_damage():
    engine, p1, p2 = game()
    ship = on_battlefield(engine, "p1", "U.S.S. Prometheus, Prototype")
    assert not ship.is_creature
    ship.counters["charge"] = 4
    engine.recompute_continuous_effects()
    assert ship.is_creature and combat.has(ship, "flying")


def test_prometheus_copies_combat_damage_to_each_other_opponent_only_at_eight():
    from mtg_analyzer.game.game_engine import GameEngine
    from tests.support.star_trek import STEP_WALK_LIBRARY, stock_library as stock

    for level, copied in ((7, 0), (8, 1)):
        engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_hand=0,
                                     starting_life=20)
        for pid in ("p1", "p2", "p3"):
            stock(engine, pid, STEP_WALK_LIBRARY)
        engine.start()
        advance_to(engine, "main1")
        ship = on_battlefield(engine, "p1", "U.S.S. Prometheus, Prototype")
        ship.counters["charge"] = level
        engine.recompute_continuous_effects()
        attack(engine, engine.state.player_by_id("p1"), ship)
        life = {pid: engine.state.player_by_id(pid).life for pid in ("p2", "p3")}
        hit = [pid for pid, value in life.items() if value < 20]
        assert len(hit) == 1 + copied  # RULE 120.3: the other opponent is hit only by the 8+ ability
        assert all(life[pid] == 20 - ship.power for pid in hit)


def test_door_of_destinies_counts_charge_counters_for_the_chosen_type():
    engine, p1, p2 = game()
    door = on_battlefield(engine, "p1", "Door of Destinies")
    door.chosen_type = "Bear"
    bear, other = vanilla(engine, "p1", "Bear Cub"), vanilla(engine, "p1", "Wolf Pup")
    bear.card.type_line, other.card.type_line = "Creature — Bear", "Creature — Wolf"
    door.counters["charge"] = 3
    engine.recompute_continuous_effects()
    assert bear.power == 5 and other.power == 2


def test_door_of_destinies_gains_a_counter_for_each_chosen_type_spell():
    engine, p1, p2 = game()
    door = on_battlefield(engine, "p1", "Door of Destinies")
    door.chosen_type = "Bear"
    cub = GameObject(Card(id="cub", name="Cub", type_line="Creature — Bear", is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.HAND)
    wolf = GameObject(Card(id="wolf", name="Wolf", type_line="Creature — Wolf", is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(cub, Zone.HAND)
    p1.add_to_zone(wolf, Zone.HAND)
    cast(engine, p1, wolf)
    assert door.counters.get("charge", 0) == 0
    cast(engine, p1, cub)
    assert door.counters.get("charge", 0) == 1


def test_defiant_phases_itself_and_one_creature_out():
    engine, p1, p2 = game("U.S.S. Defiant, Mirror Migrant")
    mine = vanilla(engine, "p1", "Mine")
    cast(engine, p1, p1.hand[0])
    if engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice["options"][0]["id"])
        engine.resolve_until_stable()
    ship = next(o for o in engine.state.battlefield + list(getattr(engine.state, "phased_out", []))
                if o.name == "U.S.S. Defiant, Mirror Migrant")
    assert ship.phased_out
    assert mine.phased_out


def test_im_a_doctor_counters_untaps_pumps_and_retypes_until_end_of_turn():
    engine, p1, p2 = game("I'm a Doctor, Not a . . .")
    creature = vanilla(engine, "p1", "Bear", 2, 2)
    creature.tapped = True
    creature.card.type_line = "Creature — Bear Warrior"
    engine.recompute_continuous_effects()
    cast(engine, p1, p1.hand[0], targets=[creature])
    assert creature.counters.get("+1/+1") == 1 and not creature.tapped
    assert creature.power == 4  # 2 + counter + until-end-of-turn pump
    assert {t.lower() for t in creature._derived_subtypes} == {"doctor"}


def test_captain_kirk_pumps_spacecraft_creatures_and_tutors_a_basic_or_the_enterprise():
    engine, p1, p2 = game("Captain Kirk, Boldly Going")
    craft = vanilla(engine, "p1", "Craft", 2, 2)
    craft.card.type_line = "Artifact Creature — Spacecraft"
    plain = vanilla(engine, "p1", "Plain", 2, 2)
    for name, tl in (("Forest", "Basic Land — Forest"), ("Starship Enterprise", "Legendary Artifact — Spacecraft"),
                     ("Nonbasic", "Land")):
        p1.library.append(GameObject(Card(id=name, name=name, type_line=tl, is_land="Land" in tl),
                                     owner_id="p1", zone=Zone.LIBRARY))
    cast(engine, p1, p1.hand[0])
    engine.recompute_continuous_effects()
    assert craft.power == 5 and plain.power == 2
    choice = engine.state.pending_choice
    assert choice is not None
    names = {o["label"] for o in choice["options"]}
    assert any("Forest" in n for n in names) and any("Starship Enterprise" in n for n in names)
    assert not any("Nonbasic" in n for n in names)


def test_inner_light_chapter_two_draws_the_combat_damage_dealt():
    engine, p1, p2 = game("The Inner Light", via_steps=True)
    stock_library(engine, "p1", 10)
    attacker = vanilla(engine, "p1", "Attacker", 3, 3)
    cast(engine, p1, p1.hand[0])  # chapter I has nothing to return
    saga = next(o for o in engine.state.battlefield if o.name == "The Inner Light")
    engine.rules.advance_sagas(p1)  # RULE 715.3c: chapter II
    for _ in range(3):
        if engine.state.pending_choice:
            options = engine.state.pending_choice["options"]
            pick = next((o["id"] for o in options if str(o.get("instance_id")) == str(attacker.instance_id)),
                        options[0]["id"])
            engine.resolve_pending_choice(pick)
        engine.resolve_until_stable()
    hand = len(p1.hand)
    attack(engine, p1, attacker)
    assert p2.life == 17 and len(p1.hand) == hand + 3


def test_gul_dukat_drains_each_opponents_life_lost_this_turn():
    engine, p1, p2 = game(via_steps=True)
    on_battlefield(engine, "p1", "Gul Dukat, Colonial Prefect")
    engine.rules.lose_life(p2, 4)
    advance_to(engine, "end")
    engine.resolve_until_stable()
    assert p2.life == 12 and p1.life == 24


def test_andromedan_automatons_fetches_every_copy_from_the_library():
    engine, p1, p2 = game("Andromedan Automatons")
    for i in range(3):
        p1.library.append(GameObject(Card(id=f"A{i}", name="Andromedan Automatons", type_line="Artifact Creature — Android"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(Card(id="other", name="Other", type_line="Land", is_land=True),
                                 owner_id="p1", zone=Zone.LIBRARY))
    cast(engine, p1, p1.hand[0])
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    found = [o["id"] for o in choice["options"] if o["id"] != "decline"]
    assert len(found) == 3  # only the named cards are offered

