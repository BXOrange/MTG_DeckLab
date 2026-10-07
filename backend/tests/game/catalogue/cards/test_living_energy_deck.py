"""Real gameplay for the Living Energy (Aetherdrift Commander) catalogue entries."""

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
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=None, **kw)
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


def _energy(engine, player="p1", amount=None):
    p = engine.state.player_by_id(player)
    if amount is not None:
        engine.rules.add_player_counters(p, amount - p.counters.get("energy", 0), "energy")
    return p.counters.get("energy", 0)


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


def test_academy_ruins_puts_an_artifact_card_from_the_graveyard_on_top_of_the_library():
    engine = _game()
    p1, _ = engine.state.players
    ruins = _card(engine, "Academy Ruins")
    relic = _filler(engine, "Relic", "Artifact", mv=2, zone=Zone.GRAVEYARD)
    _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, zone=Zone.GRAVEYARD)
    p1.mana_pool.add_many({"U": 1, "C": 1})
    _activate(engine, ruins, 0, targets=[relic])
    assert relic.zone == Zone.LIBRARY and p1.library[-1] is relic


def test_aetherflux_conduit_gets_energy_equal_to_mana_spent_and_casts_the_hand_free():
    engine = _game()
    p1, _ = engine.state.players
    conduit = _card(engine, "Aetherflux Conduit")
    spell = _filler(engine, "Pricey", "Sorcery", mv=3, zone=Zone.HAND)
    spell.card.mana_cost = {"generic": 3}
    _cast(engine, spell, {"C": 3})
    assert _energy(engine) == 3
    _energy(engine, amount=50)
    bolt = _filler(engine, "Free Spell", "Sorcery", mv=6, zone=Zone.HAND)
    _activate(engine, conduit, 0)
    assert _energy(engine) == 0 and len(p1.library) == 3  # drew seven cards
    assert bolt.instance_id in engine.state.free_cast_instance_ids
    engine.play_resolution_card(p1, bolt)
    engine.resolve_until_stable()
    assert bolt.zone == Zone.GRAVEYARD


def test_aetheric_amplifier_doubles_counters_on_a_permanent_or_the_players_own_counters():
    engine = _game()
    p1, _ = engine.state.players
    amp = _card(engine, "Aetheric Amplifier")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    bear.counters["+1/+1"] = 2
    bear.counters["shield"] = 1
    p1.mana_pool.add_many({"C": 4})
    _activate(engine, amp, 0, targets=[bear], mode=0)
    assert bear.counters["+1/+1"] == 4 and bear.counters["shield"] == 2
    amp.tapped = False
    _energy(engine, amount=3)
    p1.poison = 2
    p1.mana_pool.add_many({"C": 4})
    _activate(engine, amp, 0, mode=1)
    assert _energy(engine) == 6 and p1.poison == 4


def test_aethertide_whale_gets_six_energy_and_can_bounce_itself_for_four():
    engine = _game()
    p1, _ = engine.state.players
    whale = _put_on_battlefield(engine, "Aethertide Whale")
    assert _energy(engine) == 6
    _activate(engine, whale, 0)
    assert whale.zone == Zone.HAND and _energy(engine) == 2


def test_aetherworks_marvel_counts_permanents_dying_and_casts_free_from_the_top_six():
    engine = _game(library=10)
    p1, _ = engine.state.players
    marvel = _card(engine, "Aetherworks Marvel")
    other = _filler(engine, "Doomed", power=1, toughness=1)
    engine.state.announce_graveyard_arrivals()  # the first check only takes the zone baseline
    engine.rules.destroy(other)
    engine.resolve_until_stable()
    assert _energy(engine) == 1
    opp = _filler(engine, "Theirs", power=1, toughness=1, player="p2")
    engine.rules.destroy(opp)
    engine.resolve_until_stable()
    assert _energy(engine) == 1  # an opponent's permanent does not count
    _energy(engine, amount=6)
    gem = _filler(engine, "Top Gem", "Artifact", mv=4, zone=Zone.LIBRARY)
    _activate(engine, marvel, 0)
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "play_during_resolution"
    assert _energy(engine) == 0


def test_bespoke_battlewagon_makes_energy_taps_creatures_draws_and_animates():
    engine = _game()
    p1, _ = engine.state.players
    wagon = _card(engine, "Bespoke Battlewagon")
    victim = _filler(engine, "Victim", power=2, toughness=2, player="p2")
    _activate(engine, wagon, 0)
    assert _energy(engine) == 2
    wagon.tapped = False
    _activate(engine, wagon, 1, targets=[victim])
    assert victim.tapped and _energy(engine) == 0
    wagon.tapped = False
    _energy(engine, amount=3)
    hand = len(p1.hand)
    _activate(engine, wagon, 2)
    assert len(p1.hand) == hand + 1
    _energy(engine, amount=4)
    assert not wagon.is_creature
    _activate(engine, wagon, 3)
    continuous.recompute(engine.state)
    assert wagon.is_creature and (wagon.power, wagon.toughness) == (5, 6) and _energy(engine) == 0


def test_lightning_runner_pays_eight_for_an_untap_and_an_extra_combat():
    engine = _game()
    p1, _ = engine.state.players
    runner = _card(engine, "Lightning Runner")
    tapped = _filler(engine, "Tapped", power=1, toughness=1)
    tapped.tapped = True
    _energy(engine, amount=6)
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": runner, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    _answer(engine, pick=lambda c: "pay" if any(o["id"] == "pay" for o in c["options"]) else "decline")
    assert _energy(engine) == 0 and not tapped.tapped
    assert engine.state.pending_extra_combats == [False]  # one additional combat phase, no extra main phase


def test_lightning_runner_declined_payment_keeps_the_energy():
    engine = _game()
    p1, _ = engine.state.players
    runner = _card(engine, "Lightning Runner")
    _energy(engine, amount=0)
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": runner, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    assert _energy(engine) == 2 and engine.state.pending_choice is None  # can't afford eight: no offer


def test_nissa_worldsoul_speaker_gives_energy_on_landfall_and_casts_permanents_for_eight():
    engine = _game()
    p1, _ = engine.state.players
    nissa = _card(engine, "Nissa, Worldsoul Speaker")
    land = _filler(engine, "Island", "Basic Land — Island", zone=Zone.HAND)
    engine.state.current_step = "main1"
    engine.play_land(p1, land)
    engine.resolve_until_stable()
    assert _energy(engine) == 2
    _energy(engine, amount=8)
    golem = _filler(engine, "Golem", "Artifact Creature — Golem", mv=5, power=3, toughness=3, zone=Zone.HAND)
    golem.card.mana_cost = {"generic": 5}
    engine.state.current_step = "main1"
    engine.cast_spell(p1, golem, targets=None, target_groups=None, alt_cost=True)
    engine.resolve_until_stable()
    assert golem.zone == Zone.BATTLEFIELD and _energy(engine) == 0 and nissa.zone == Zone.BATTLEFIELD


def test_nissa_does_not_offer_the_energy_cost_for_an_instant_or_sorcery():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Nissa, Worldsoul Speaker")
    _energy(engine, amount=8)
    sorcery = _filler(engine, "Spell", "Sorcery", mv=2, zone=Zone.HAND)
    engine.state.current_step = "main1"
    assert not engine.can_cast(p1, sorcery, alt_cost=True)


def test_triplicate_titan_leaves_three_golems_with_one_keyword_each():
    engine = _game()
    titan = _card(engine, "Triplicate Titan")
    engine.rules.destroy(titan)
    engine.resolve_until_stable()
    golems = _named(engine, "Golem")
    continuous.recompute(engine.state)
    assert len(golems) == 3 and all((g.power, g.toughness) == (3, 3) and g.card.is_artifact for g in golems)
    assert sorted(next(k for k in ("flying", "vigilance", "trample") if combat.has(g, k)) for g in golems) == [
        "flying", "trample", "vigilance"]


def test_stridehangar_automaton_adds_a_thopter_to_artifact_token_creation_and_pumps_thopters():
    engine = _game()
    _card(engine, "Stridehangar Automaton")
    ctx = engine.rules
    treasure = CardDatabase  # placeholder to keep import used
    from mtg_analyzer.services.token_database import default_token_database, synthesize_token_card

    ctx.create_token("p1", default_token_database().get_token("Treasure"), 1)
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    thopters = _named(engine, "Thopter")
    assert len(_named(engine, "Treasure")) == 1 and len(thopters) == 1
    assert combat.has(thopters[0], "flying") and (thopters[0].power, thopters[0].toughness) == (2, 2)
    # A non-artifact token creation gets nothing extra, and the extra Thopter does not itself trigger another.
    ctx.create_token("p1", synthesize_token_card("Soldier", power=1, toughness=1, colors=["W"]), 1)
    engine.resolve_until_stable()
    assert len(_named(engine, "Thopter")) == 1
    # An artifact *creature* token (a Servo) also counts, once per creation.
    ctx.create_token("p1", synthesize_token_card("Servo", power=1, toughness=1, is_artifact=True), 2)
    engine.resolve_until_stable()
    assert len(_named(engine, "Servo")) == 2 and len(_named(engine, "Thopter")) == 2


def test_midnight_clock_adds_counters_each_upkeep_and_resets_the_game_on_the_twelfth():
    engine = _game(library=12)
    p1, p2 = engine.state.players
    clock = _card(engine, "Midnight Clock")
    for i in range(3):
        _filler(engine, f"Hand{i}", "Sorcery", zone=Zone.HAND)
    _filler(engine, "Dead", "Sorcery", zone=Zone.GRAVEYARD)
    _step(engine, "upkeep", "p1")
    _step(engine, "upkeep", "p2")
    assert clock.counters.get("hour") == 2
    p1.mana_pool.add_many({"U": 1, "C": 2})
    for _ in range(9):
        p1.mana_pool.add_many({"U": 1, "C": 2})
        _activate(engine, clock, 0)
    assert clock.counters.get("hour") == 11
    p1.mana_pool.add_many({"U": 1, "C": 2})
    _activate(engine, clock, 0)
    assert clock.zone == Zone.EXILE  # the twelfth hour counter exiled it
    assert len(p1.hand) == 7 and not p1.graveyard


def test_peema_aether_seer_gets_energy_for_the_greatest_power_and_forces_a_block():
    engine = _game()
    p1, p2 = engine.state.players
    _filler(engine, "Big", power=5, toughness=5)
    peema = _put_on_battlefield(engine, "Peema Aether-Seer")
    assert _energy(engine) == 5
    blocker = _filler(engine, "Blocker", power=1, toughness=3, player="p2")
    attacker = _filler(engine, "Attacker", power=2, toughness=2)
    _activate(engine, peema, 0, targets=[blocker])
    assert _energy(engine) == 2
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    engine.declare_attackers(p1, [{"attacker": attacker, "defender": engine.legal_defenders_for(p1)[0]}])
    engine.resolve_until_stable()
    state.current_step = "declare_blockers"
    try:
        engine.declare_blockers(p2, [])
        engine._enforce_block_requirements()
    except ValueError as exc:
        assert "must block" in str(exc)
    else:
        raise AssertionError("the forced blocker may not skip blocking")


def test_pia_nalaar_makes_energy_from_artifact_creature_damage_and_a_crewable_x_x_vehicle():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Pia Nalaar, Chief Mechanic")
    _energy(engine, amount=5)
    _step(engine, "end", "p1")
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_energy_then"
    assert [o["id"] for o in choice["options"]] == ["pay_x:5", "pay_x:4", "pay_x:3", "pay_x:2", "pay_x:1", "decline"]
    engine.resolve_pending_choice("pay_x:3")
    jet = _named(engine, "Nalaar Aetherjet")[0]
    continuous.recompute(engine.state)
    assert _energy(engine) == 2 and jet.card.is_artifact and not jet.is_creature
    assert (jet.card.vehicle_power, jet.card.vehicle_toughness) == (3, 3)
    assert jet.activated_abilities, "Crew 2 is bound on the token"
    crew = _filler(engine, "Crew", power=2, toughness=2)
    engine.state.current_step = "main1"
    engine.activate_ability(p1, jet, 0, tap_choices=[crew.instance_id])
    engine.resolve_until_stable()
    continuous.recompute(engine.state)
    assert jet.is_creature and (jet.power, jet.toughness) == (3, 3) and combat.has(jet, "flying")


def test_pia_nalaar_can_decline_the_payment():
    engine = _game()
    _card(engine, "Pia Nalaar, Chief Mechanic")
    _energy(engine, amount=2)
    _step(engine, "end", "p1")
    engine.resolve_pending_choice("decline")
    assert not _named(engine, "Nalaar Aetherjet") and _energy(engine) == 2


def test_pia_nalaar_triggers_on_combat_damage_by_artifact_creatures():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Pia Nalaar, Chief Mechanic")
    bot = _filler(engine, "Bot", "Artifact Creature — Construct", power=2, toughness=2)
    _attack_and_damage(engine, [bot])
    assert _energy(engine) == 2


def _attack_and_damage(engine, attackers):
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    p1 = state.player_by_id("p1")
    first = engine.legal_defenders_for(p1)[0]
    engine.declare_attackers(p1, [{"attacker": a, "defender": first} for a in attackers])
    engine.resolve_until_stable()
    for step in ("declare_blockers", "combat_damage"):
        state.current_step = step
    engine._step_combat_damage()
    engine.resolve_until_stable()


def test_rampaging_aetherhood_gets_energy_for_its_power_and_turns_it_into_counters():
    engine = _game()
    hood = _card(engine, "Rampaging Aetherhood")
    _step(engine, "upkeep", "p1")
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "pay_energy_then"
    assert _energy(engine) == hood.power
    engine.resolve_pending_choice(f"pay_x:{hood.power}")
    continuous.recompute(engine.state)
    assert hood.counters.get("+1/+1") == 4 and _energy(engine) == 0


def test_territorial_aetherkite_pays_x_to_deal_x_to_each_other_creature():
    engine = _game()
    p1, p2 = engine.state.players
    mine = _filler(engine, "Mine", power=1, toughness=4)
    theirs = _filler(engine, "Theirs", power=1, toughness=2, player="p2")
    kite = _put_on_battlefield(engine, "Territorial Aetherkite")
    assert _energy(engine) == 2
    engine.resolve_pending_choice("pay_x:2")
    engine.resolve_until_stable()
    assert theirs.zone == Zone.GRAVEYARD and mine.damage_marked == 2 and kite.damage_marked == 0 and _energy(engine) == 0


def test_saheeli_radiant_creator_gets_energy_for_artifacts_and_copies_a_permanent_as_a_five_five():
    engine = _game()
    p1, p2 = engine.state.players
    saheeli = _card(engine, "Saheeli, Radiant Creator")
    rock = _filler(engine, "Rock", "Artifact", mv=1, zone=Zone.HAND)
    _cast(engine, rock, {"C": 1})
    assert _energy(engine) == 1
    _energy(engine, amount=3)
    elf = _filler(engine, "Elf", "Creature — Elf", power=1, toughness=1)
    _step(engine, "begin_combat", "p1")
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice("pay" if "pay" in ids else (str(elf.instance_id) if str(elf.instance_id) in ids else ids[0]))
    engine.resolve_until_stable()
    copies = [o for o in _named(engine, "Elf") if o is not elf]
    continuous.recompute(engine.state)
    assert len(copies) == 1 and _energy(engine) == 0
    token = copies[0]
    assert token.is_token and (token.power, token.toughness) == (5, 5) and token.card.is_artifact
    engine._fire_delayed_triggers("end")
    engine.resolve_until_stable()
    assert token.zone != Zone.BATTLEFIELD  # sacrificed at the beginning of the next end step
    assert saheeli.zone == Zone.BATTLEFIELD


def test_saheeli_sublime_artificer_makes_servos_and_turns_an_artifact_into_a_copy():
    engine = _game()
    p1, p2 = engine.state.players
    saheeli = _card(engine, "Saheeli, Sublime Artificer")
    saheeli.counters["loyalty"] = 5
    spell = _filler(engine, "Zap", "Instant", mv=1, zone=Zone.HAND)
    _cast(engine, spell, {"C": 1})
    assert len(_named(engine, "Servo")) == 1
    rock = _filler(engine, "Rock", "Artifact", mv=1)
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    ability = next(i for i, a in enumerate(saheeli.activated_abilities))
    _activate(engine, saheeli, ability, targets=[rock, bear])
    continuous.recompute(engine.state)
    assert rock.name == "Bear" and rock.card.is_artifact and rock.is_creature
    assert (rock.power, rock.toughness) == (2, 2)
    _step(engine, "cleanup", "p1")
    engine.state.current_step = "cleanup"
    engine._step_cleanup()
    continuous.recompute(engine.state)
    assert rock.name == "Rock" and not rock.is_creature


def test_combustible_gearhulk_opponent_chooses_cards_or_a_damage_burst():
    for decline_draw, expected in ((False, "draw"), (True, "burn")):
        engine = _game(library=10)
        p1, p2 = engine.state.players
        for i in range(3):
            _filler(engine, f"Top{i}", "Sorcery", mv=4, zone=Zone.LIBRARY)
        hand, life, library = len(p1.hand), p2.life, len(p1.library)
        _put_on_battlefield(engine, "Combustible Gearhulk")
        for _ in range(4):
            choice = engine.state.pending_choice
            if choice is None:
                break
            ids = [str(o["id"]) for o in choice.get("options", [])]
            if "p2" in ids or "opponent" in ids:
                engine.resolve_pending_choice("p2" if "p2" in ids else "opponent")
            elif decline_draw:
                engine.resolve_pending_choice("decline")
            else:
                engine.resolve_pending_choice("pay")
        engine.resolve_until_stable()
        if expected == "draw":
            assert len(p1.hand) == hand + 3 and p2.life == life
        else:
            assert len(p1.library) == library - 3 and p2.life == life - 12


def test_confiscation_coup_pays_energy_equal_to_the_targets_mana_value_to_steal_it():
    engine = _game()
    p1, p2 = engine.state.players
    prize = _filler(engine, "Prize", "Artifact Creature — Golem", mv=5, power=4, toughness=4, player="p2")
    spell = _card(engine, "Confiscation Coup", zone=Zone.HAND)
    _cast(engine, spell, {"U": 2, "C": 3}, targets=[prize])
    assert _energy(engine) == 4 and engine.state.pending_choice is None  # cannot afford the five it costs
    assert prize.controller_id == "p2"
    cheap = _filler(engine, "Cheap", "Artifact Creature — Golem", mv=3, power=1, toughness=1, player="p2")
    again = _card(engine, "Confiscation Coup", zone=Zone.HAND)
    _cast(engine, again, {"U": 2, "C": 3}, targets=[cheap])
    assert engine.state.pending_choice["kind"] == "pay_energy_then"
    engine.resolve_pending_choice("pay")
    assert cheap.controller_id == "p1" and _energy(engine) == 8 - 3 + 0


def test_druid_of_purification_lets_every_player_choose_an_artifact_or_enchantment_to_destroy():
    engine = _game()
    p1, p2 = engine.state.players
    mine = _filler(engine, "Mine", "Artifact", mv=1)
    theirs_a = _filler(engine, "Theirs A", "Artifact", mv=1, player="p2")
    theirs_e = _filler(engine, "Theirs E", "Enchantment", mv=1, player="p2")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2, player="p2")
    _put_on_battlefield(engine, "Druid of Purification")
    seen = []

    def pick(choice):
        ids = [str(o["id"]) for o in choice.get("options", [])]
        seen.append(ids)
        wanted = (theirs_a, theirs_e)[len(seen) - 1]  # each player picks a different permanent
        return str(wanted.instance_id) if str(wanted.instance_id) in ids else "decline"

    _answer(engine, pick=pick)
    assert mine.zone == Zone.BATTLEFIELD and bear.zone == Zone.BATTLEFIELD
    assert theirs_a.zone == Zone.GRAVEYARD and theirs_e.zone == Zone.GRAVEYARD
    assert all(str(mine.instance_id) not in ids for ids in seen)
