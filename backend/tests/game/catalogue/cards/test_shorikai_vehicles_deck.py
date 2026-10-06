"""Real gameplay for the Shorikai Vehicles catalogue entries."""

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "",
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 3, "U": 3, "B": 3, "R": 3, "G": 3, "C": 5}


def _attack_and_damage(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p1 = state.player_by_id("p1")
    first = engine.legal_defenders_for(p1)[0]
    engine.declare_attackers(p1, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def _gy(engine, name, player="p1"):
    return _card(engine, name, player, zone=Zone.GRAVEYARD)


def _gy_filler(engine, type_line, name="GY", power=None, toughness=None, player="p1"):
    return _filler(engine, name=name, type_line=type_line, power=power, toughness=toughness, player=player,
                   zone=Zone.GRAVEYARD)


def _walker(engine, name, loyalty, player="p1"):
    pw = _card(engine, name, player)
    pw.counters["loyalty"] = loyalty
    return pw


def _loyalty(engine, pw, cost, player="p1", **kw):
    index = next(i for i, a in enumerate(pw.activated_abilities) if getattr(getattr(a, "cost", None), "loyalty", None) == cost)
    pw.activated_loyalty_this_turn = False
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.player_by_id(player), pw, index, **kw)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _vehicle(engine, name, power=3, toughness=3, player="p1"):
    return _card(engine, name, player)


def _crew(engine, vehicle, player="p1", **kw):
    index = next(i for i, a in enumerate(vehicle.activated_abilities + vehicle.granted_activated_abilities)
                 if getattr(getattr(a, "cost", None), "crew_power", None))
    engine.state.current_step = "main1"
    engine.activate_ability(engine.state.player_by_id(player), vehicle, index, **kw)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()


def _declare(engine, attackers, player="p1"):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p = state.player_by_id(player)
    first = engine.legal_defenders_for(p)[0]
    engine.declare_attackers(p, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()


def test_smugglers_copter_loots_when_it_attacks():
    engine = _game(library=10)
    p1 = engine.state.player_by_id("p1")
    copter = _vehicle(engine, "Smuggler's Copter")
    crew = _filler(engine, "Crew", "Creature — Bear", power=1, toughness=1)
    _crew(engine, copter)
    assert copter.is_creature and crew.tapped
    hand = len(p1.hand)
    _declare(engine, [copter])
    engine.resolve_pending_choice("yes")
    _answer(engine)
    assert len(p1.hand) == hand and len(p1.graveyard) == 1  # drew one, discarded one


def _pilots(engine, player="p1"):
    return [o for o in engine.state.battlefield if o.name == "Pilot" and o.controller_id == player]


def test_a_pilot_crews_as_though_its_power_were_two_greater():
    engine = _game()
    shorikai = _vehicle(engine, "Shorikai, Genesis Engine")  # Crew 8
    engine.rules._apply_effect_specs([{"type": "create_token", "params": {
        "count": 3, "power": 1, "toughness": 1, "colors": [], "subtypes": ["Pilot"], "token_name": "Pilot",
        "oracle_text": "This token crews Vehicles as though its power were 2 greater."}}], shorikai)
    pilots = _pilots(engine)
    assert len(pilots) == 3
    # Printed power alone is 3 < 8; with the +2 bonus each Pilot crews for 3, so all three together (9 ≥ 8) crew Shorikai.
    _crew(engine, shorikai)
    assert shorikai.is_creature and all(p.tapped for p in pilots)


def test_shorikai_loots_and_makes_a_pilot():
    engine = _game(library=10)
    p1 = engine.state.player_by_id("p1")
    shorikai = _vehicle(engine, "Shorikai, Genesis Engine")
    p1.mana_pool.add_many({"C": 1})
    index = next(i for i, a in enumerate(shorikai.activated_abilities) if not getattr(a.cost, "crew_power", None))
    engine.state.current_step = "main1"
    engine.activate_ability(p1, shorikai, index)
    engine.resolve_until_stable()
    _answer(engine)
    assert len(_pilots(engine)) == 1 and len(p1.hand) == 1 and len(p1.graveyard) == 1  # drew 2, discarded 1


def test_prodigys_prototype_makes_a_pilot_when_vehicles_attack():
    engine = _game()
    proto = _vehicle(engine, "Prodigy's Prototype")
    _filler(engine, "Crew", "Creature — Bear", power=2, toughness=2)
    _crew(engine, proto)
    _declare(engine, [proto])
    assert len(_pilots(engine)) == 1


def test_reckoner_bankbuster_draws_and_on_the_last_counter_makes_a_treasure_and_a_pilot():
    engine = _game(library=10)
    p1 = engine.state.player_by_id("p1")
    bank = _card(engine, "Reckoner Bankbuster", zone=Zone.HAND)
    _cast(engine, bank, {"C": 2})
    assert bank.counters.get("charge") == 3
    index = next(i for i, a in enumerate(bank.activated_abilities) if not getattr(a.cost, "crew_power", None))
    for expected in (2, 1, 0):
        bank.tapped = False
        p1.mana_pool.add_many({"C": 2})
        engine.state.current_step = "main1"
        engine.activate_ability(p1, bank, index)
        engine.resolve_until_stable()
        assert bank.counters.get("charge", 0) == expected
    assert len(p1.hand) == 3
    assert any(o.name == "Treasure" for o in engine.state.battlefield) and len(_pilots(engine)) == 1


def test_digsite_engineer_pays_two_for_a_construct_that_grows_with_artifacts():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Digsite Engineer")
    rock = _filler(engine, "Rock", "Artifact", mv=1, zone=Zone.HAND)
    p1.mana_pool.add_many({"C": 3})
    _cast(engine, rock, {"C": 1})
    engine.resolve_pending_choice("pay")
    construct = [o for o in _named(engine, "Construct") if o.is_token]
    engine.recompute_continuous_effects()
    assert len(construct) == 1 and construct[0].power == 2  # the Rock and the Construct itself


def test_peacewalker_colossus_animates_another_vehicle_with_its_printed_pt():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    colossus = _vehicle(engine, "Peacewalker Colossus")
    copter = _vehicle(engine, "Smuggler's Copter")
    assert not copter.is_creature
    p1.mana_pool.add_many({"W": 1, "C": 1})
    index = next(i for i, a in enumerate(colossus.activated_abilities) if not getattr(a.cost, "crew_power", None))
    engine.state.current_step = "main1"
    engine.activate_ability(p1, colossus, index, targets=[copter])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert copter.is_creature and (copter.power, copter.toughness) == (3, 3)
    assert not colossus.is_creature  # "another" Vehicle only


def test_mobilizer_mech_animates_another_vehicle_when_it_becomes_crewed():
    engine = _game()
    mech = _vehicle(engine, "Mobilizer Mech")
    copter = _vehicle(engine, "Smuggler's Copter")
    _filler(engine, "Crew", "Creature — Bear", power=3, toughness=3)
    _crew(engine, mech)
    _answer(engine, pick=lambda c: str(copter.instance_id) if any(str(o["id"]) == str(copter.instance_id) for o in c["options"]) else None)
    engine.recompute_continuous_effects()
    assert mech.is_creature and copter.is_creature


def test_mech_hangar_animates_any_vehicle():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    hangar = _card(engine, "Mech Hangar")
    theirs = _card(engine, "Smuggler's Copter", player="p2")
    p1.mana_pool.add_many({"C": 3})
    engine.state.current_step = "main1"
    engine.activate_ability(p1, hangar, 0, targets=[theirs])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert theirs.is_creature


def test_mech_hangar_makes_colorless_or_restricted_any_color_mana():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    engine = _game()
    hangar = _card(engine, "Mech Hangar")
    abilities = mana_abilities_for(hangar)
    assert len(abilities) == 2


def test_kotori_gives_every_vehicle_crew_two_and_buffs_an_artifact_creature_at_combat():
    engine = _game()
    kotori = _card(engine, "Kotori, Pilot Prodigy")
    garrison = _vehicle(engine, "Smuggler's Copter")
    # Strip the Copter's own Crew 1 so only Kotori's grant remains.
    garrison.activated_abilities[:] = [a for a in garrison.activated_abilities if not getattr(a.cost, "crew_power", None)]
    engine.recompute_continuous_effects()
    assert any(getattr(a.cost, "crew_power", None) == 2 for a in garrison.granted_activated_abilities)
    _crew(engine, garrison)  # Kotori (power 2) crews alone
    assert garrison.is_creature and kotori.tapped

    _step(engine, "begin_combat")
    _answer(engine, pick=lambda c: str(garrison.instance_id) if any(str(o["id"]) == str(garrison.instance_id) for o in c["options"]) else None)
    engine.recompute_continuous_effects()
    assert "lifelink" in garrison.granted_keywords and "vigilance" in garrison.granted_keywords


def test_born_to_drive_channel_makes_two_pilots_from_hand():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    drive = _card(engine, "Born to Drive", zone=Zone.HAND)
    p1.mana_pool.add_many({"W": 1, "C": 2})
    engine.state.current_step = "main1"
    engine.activate_ability(p1, drive, 0)
    engine.resolve_until_stable()
    assert len(_pilots(engine)) == 2 and drive in p1.graveyard


def test_born_to_drive_buffs_an_enchanted_creature_by_creatures_and_vehicles():
    engine = _game()
    host = _filler(engine, "Host", "Creature — Bear", power=1, toughness=1)
    _vehicle(engine, "Smuggler's Copter")
    _filler(engine, "Other", "Creature — Bear", power=1, toughness=1)
    drive = _card(engine, "Born to Drive")
    drive.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    assert (host.power, host.toughness) == (1 + 3, 1 + 3)  # two creatures + the Vehicle (not a creature now)... host, Other, Copter


def test_mutavault_becomes_a_2_2_creature_land_with_every_creature_type():
    from mtg_analyzer.game import continuous

    engine = _game()
    p1 = engine.state.player_by_id("p1")
    vault = _card(engine, "Mutavault")
    p1.mana_pool.add_many({"C": 1})
    engine.state.current_step = "main1"
    engine.activate_ability(p1, vault, 0)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert vault.is_creature and vault.is_land and (vault.power, vault.toughness) == (2, 2)
    assert continuous.has_subtype(vault, "Goblin") and continuous.has_subtype(vault, "Dragon")


def test_intruder_alarm_keeps_creatures_tapped_until_a_creature_enters():
    engine = _game()
    _card(engine, "Intruder Alarm")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    rock = _filler(engine, "Rock", "Artifact")
    bear.tapped = rock.tapped = True
    engine._step_untap()
    assert bear.tapped and not rock.tapped
    newcomer = _filler(engine, "New", "Creature — Bear", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, newcomer, {"C": 1})
    assert not bear.tapped  # whenever a creature enters, untap all creatures


def test_unwinding_clock_untaps_your_artifacts_during_other_players_untap_steps():
    engine = _game()
    clock = _card(engine, "Unwinding Clock")
    rock = _filler(engine, "Rock", "Artifact")
    rock.tapped = True
    engine.state.active_player_index = 1  # an opponent's untap step
    engine._step_untap()
    assert not rock.tapped


def test_the_wanderer_prevents_noncombat_damage_to_you_and_your_other_permanents_but_not_combat_damage():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    wanderer = _walker(engine, "The Wanderer", 5)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    source = _filler(engine, "Shooter", "Creature — Bear", power=1, toughness=1, player="p2")
    life = p1.life
    engine.rules.deal_damage(p1, 3, source=source, combat=False)
    engine.rules.deal_damage(bear, 3, source=source, combat=False)
    assert p1.life == life and bear.damage_marked == 0
    engine.rules.deal_damage(p1, 3, source=source, combat=True)
    assert p1.life == life - 3


def test_the_wanderer_minus_two_exiles_a_creature_with_power_four_or_greater():
    engine = _game()
    wanderer = _walker(engine, "The Wanderer", 5)
    big = _filler(engine, "Big", "Creature — Giant", power=4, toughness=4, player="p2")
    small = _filler(engine, "Small", "Creature — Bear", power=3, toughness=3, player="p2")
    _loyalty(engine, wanderer, -2, targets=[big])
    assert big.zone == Zone.EXILE and small in engine.state.battlefield


def test_rebbec_protects_artifacts_from_sources_matching_a_mana_value_among_your_artifacts():
    from mtg_analyzer.game import combat

    engine = _game()
    _card(engine, "Rebbec, Architect of Ascension")
    rock = _filler(engine, "Rock", "Artifact", mv=2)
    peer = _filler(engine, "Peer", "Creature — Bear", mv=2, power=1, toughness=1, player="p2")
    other = _filler(engine, "Other", "Creature — Bear", mv=5, power=1, toughness=1, player="p2")
    engine.recompute_continuous_effects()
    assert combat.is_protected_from(rock, peer) and not combat.is_protected_from(rock, other)


def test_the_millennium_calendar_counts_untapped_permanents_doubles_and_eventually_wins():
    engine = _game()
    p1, p2 = engine.state.players
    calendar = _card(engine, "The Millennium Calendar")
    rocks = [_filler(engine, f"Rock{i}", "Artifact") for i in range(3)]
    for r in rocks:
        r.tapped = True
    engine._step_untap()
    engine.resolve_until_stable()
    assert calendar.counters.get("time") == 3

    calendar.tapped = False
    p1.mana_pool.add_many({"C": 2})
    engine.state.current_step = "main1"
    engine.activate_ability(p1, calendar, 0)
    engine.resolve_until_stable()
    assert calendar.counters.get("time") == 6

    calendar.counters["time"] = 600
    calendar.tapped = False
    p1.mana_pool.add_many({"C": 2})
    life = p2.life
    engine.activate_ability(p1, calendar, 0)  # 600 → 1200 ≥ 1000
    engine.resolve_until_stable()
    assert calendar.zone == Zone.GRAVEYARD and p2.life == life - 1000


def test_dermotaxi_imprints_a_graveyard_creature_and_copies_it_until_end_of_turn():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    victim = _gy_filler(engine, "Creature — Dragon", "Dead Dragon", power=5, toughness=5, player="p2")
    taxi = _card(engine, "Dermotaxi", zone=Zone.HAND)
    _cast(engine, taxi, {"C": 2})
    _answer(engine)
    assert victim.zone == Zone.EXILE and taxi.linked_exile_id == victim.instance_id

    a = _filler(engine, "A", "Creature — Bear", power=1, toughness=1)
    b = _filler(engine, "B", "Creature — Bear", power=1, toughness=1)
    engine.state.current_step = "main1"
    engine.activate_ability(p1, taxi, 0, tap_choices=[a.instance_id, b.instance_id])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert a.tapped and b.tapped
    assert taxi.is_creature and (taxi.power, taxi.toughness) == (5, 5) and "vehicle" in taxi.card.type_line.lower()


def test_mechtitan_core_exiles_five_makes_a_10_10_and_returns_the_others_tapped_when_it_leaves():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    core = _vehicle(engine, "Mechtitan Core")
    others = [_filler(engine, f"Golem{i}", "Artifact Creature — Golem", power=1, toughness=1) for i in range(3)]
    copter = _vehicle(engine, "Smuggler's Copter")
    spare = _filler(engine, "Spare", "Creature — Bear", power=1, toughness=1)  # not an artifact creature or Vehicle
    p1.mana_pool.add_many({"C": 5})
    index = next(i for i, a in enumerate(core.activated_abilities) if getattr(a.cost, "exile_others", None))
    engine.state.current_step = "main1"
    engine.activate_ability(p1, core, index, tap_choices=[o.instance_id for o in others] + [copter.instance_id])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    titan = next(o for o in engine.state.battlefield if o.name == "Mechtitan")
    assert (titan.power, titan.toughness) == (10, 10) and titan.is_token
    assert core.zone == Zone.EXILE and all(o.zone == Zone.EXILE for o in others + [copter]) and spare.zone == Zone.BATTLEFIELD
    assert combat.has(titan, "flying") and combat.has(titan, "lifelink") and len(titan.colors) == 5

    engine.rules.destroy(titan)
    engine.resolve_until_stable()
    assert core.zone == Zone.EXILE  # "except this card"
    assert all(o.zone == Zone.BATTLEFIELD and o.tapped for o in others + [copter])
