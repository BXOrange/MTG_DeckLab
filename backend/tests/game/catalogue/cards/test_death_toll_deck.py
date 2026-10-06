"""Real gameplay for the Death Toll (Duskmourn: House of Horror Commander) catalogue entries."""

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


def test_whispersilk_cloak_grants_unblockable_and_shroud_to_equipped_creature():
    engine = _game()
    cloak = _card(engine, "Whispersilk Cloak")
    bear = _filler(engine, "Bear", "Creature — Bear", power=2, toughness=2)
    bear.attacking = True
    cloak.attached_to = bear.instance_id
    engine.recompute_continuous_effects()
    assert combat.has(bear, "cant_be_blocked") and combat.has(bear, "shroud")


def test_carrion_grub_power_tracks_greatest_creature_card_power_in_graveyard():
    engine = _game()
    grub = _card(engine, "Carrion Grub")
    engine.recompute_continuous_effects()
    base = grub.power
    _gy_filler(engine, "Creature — Giant", "Big", power=6, toughness=6)
    _gy_filler(engine, "Creature — Bear", "Small", power=2, toughness=2)
    _gy_filler(engine, "Sorcery", "Spell")
    engine.recompute_continuous_effects()
    assert grub.power == base + 6


def test_deluge_of_doom_counts_distinct_card_types_in_graveyard():
    engine = _game()
    deluge = _card(engine, "Deluge of Doom", zone=Zone.HAND)
    _gy_filler(engine, "Sorcery", "S1")
    _gy_filler(engine, "Sorcery", "S2")
    _gy_filler(engine, "Land", "L1")
    mine = _filler(engine, "Mine", "Creature — Bear", power=3, toughness=3)
    theirs = _filler(engine, "Theirs", "Creature — Bear", power=2, toughness=2, player="p2")
    _cast(engine, deluge, {"B": 3})
    # Sorcery + Land in the graveyard, plus Deluge itself (a Sorcery, already counted) → X = 2.
    assert mine.toughness == 1 and theirs not in engine.state.battlefield


def test_cemetery_tampering_hides_a_card_and_plays_it_free_at_twenty_graveyard_cards():
    engine = _game(library=40)
    p1 = engine.state.player_by_id("p1")
    tampering = _put_on_battlefield(engine, "Cemetery Tampering")
    _answer(engine)  # hideaway pick
    assert len(tampering.hideaway_exile_ids) == 1
    for i in range(19):
        _gy_filler(engine, "Sorcery", f"Junk{i}")
    _step(engine, "upkeep")
    assert engine.state.pending_choice and engine.state.pending_choice["kind"] == "composite_optional"
    engine.resolve_pending_choice("yes")
    # 19 + 3 milled = 22 ≥ 20 → the exiled card may be played for free.
    choice = engine.state.pending_choice
    assert choice and choice["kind"] == "play_during_resolution"


def test_cemetery_tampering_below_threshold_offers_nothing():
    engine = _game(library=40)
    tampering = _put_on_battlefield(engine, "Cemetery Tampering")
    _answer(engine)
    _step(engine, "upkeep")
    engine.resolve_pending_choice("yes")
    assert engine.state.pending_choice is None
    assert len(engine.state.player_by_id("p1").graveyard) == 3


def test_convert_to_slime_destroys_each_chosen_target_and_sizes_the_ooze_by_total_mana_value_with_delirium():
    engine = _game()
    slime = _card(engine, "Convert to Slime", zone=Zone.HAND)
    artifact = _filler(engine, "Rock", "Artifact", mv=2, player="p2")
    creature = _filler(engine, "Bear", "Creature — Bear", mv=3, power=2, toughness=2, player="p2")
    enchant = _filler(engine, "Aura", "Enchantment", mv=4, player="p2")
    for tl, n in (("Land", "L"), ("Instant", "I"), ("Sorcery", "S"), ("Creature — Elf", "E")):  # my graveyard: delirium
        _gy_filler(engine, tl, n, power=1 if "Creature" in tl else None, toughness=1 if "Creature" in tl else None)
    _cast(engine, slime, {"B": 3, "G": 3, "C": 5}, targets=[artifact, creature, enchant], groups=[[artifact], [creature], [enchant]])
    assert not {artifact, creature, enchant} & set(engine.state.battlefield)
    ooze = _named(engine, "Ooze")
    assert len(ooze) == 1 and (ooze[0].power, ooze[0].toughness) == (9, 9)


def test_convert_to_slime_without_delirium_makes_no_ooze():
    engine = _game()
    slime = _card(engine, "Convert to Slime", zone=Zone.HAND)
    creature = _filler(engine, "Bear", "Creature — Bear", mv=3, power=2, toughness=2, player="p2")
    _cast(engine, slime, {"B": 3, "G": 3, "C": 5}, targets=[creature], groups=[[], [creature], []])
    assert creature not in engine.state.battlefield and not _named(engine, "Ooze")


def test_deadbridge_chant_mills_ten_then_returns_a_random_graveyard_card_by_type():
    engine = _game(library=30)
    p1 = engine.state.player_by_id("p1")
    _put_on_battlefield(engine, "Deadbridge Chant")
    assert len(p1.graveyard) == 10
    p1.graveyard.clear()
    bear = _gy_filler(engine, "Creature — Bear", "Bear", power=2, toughness=2)
    _step(engine, "upkeep")
    assert bear in engine.state.battlefield and not p1.graveyard

    sorcery = _gy_filler(engine, "Sorcery", "Spell")
    _step(engine, "upkeep")
    assert sorcery in p1.hand and sorcery not in p1.graveyard


def test_moldgraf_monstrosity_exiles_itself_and_returns_two_random_creatures_when_it_dies():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    moldgraf = _card(engine, "Moldgraf Monstrosity")
    creatures = [_gy_filler(engine, "Creature — Bear", f"Bear{i}", power=1, toughness=1) for i in range(3)]
    _gy_filler(engine, "Sorcery", "Spell")
    engine.rules.destroy(moldgraf)
    engine.resolve_until_stable()
    assert moldgraf.zone == Zone.EXILE
    assert sum(c in engine.state.battlefield for c in creatures) == 2
    assert all(o.name != "Moldgraf Monstrosity" for o in p1.graveyard)


def test_demonic_covenant_draws_when_demons_attack_a_player_and_makes_a_demon_each_end_step():
    engine = _game(library=40)
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Demonic Covenant")
    demon = _filler(engine, "Imp", "Creature — Demon", power=2, toughness=2)
    hand, life = len(p1.hand), p1.life
    _attack_and_damage(engine, [demon])
    assert len(p1.hand) == hand + 1 and p1.life == life - 1

    _step(engine, "end")
    tokens = [o for o in _named(engine, "Demon") if o.is_token]
    assert len(tokens) == 1 and (tokens[0].power, tokens[0].toughness) == (5, 5)
    assert len(p1.graveyard) == 3  # two milled Forests share all their types, so the Covenant was sacrificed too


def test_demonic_covenant_is_sacrificed_only_when_the_two_milled_cards_share_all_their_types():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    covenant = _card(engine, "Demonic Covenant")
    for name in ("A", "B"):
        _filler(engine, name, "Sorcery", zone=Zone.LIBRARY)
    _step(engine, "end")
    assert covenant not in engine.state.battlefield

    engine = _game(library=0)
    covenant = _card(engine, "Demonic Covenant")
    _filler(engine, "A", "Sorcery", zone=Zone.LIBRARY)
    _filler(engine, "B", "Instant", zone=Zone.LIBRARY)
    _step(engine, "end")
    assert covenant in engine.state.battlefield


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


def test_grist_plus_one_repeats_while_an_insect_card_is_milled_and_adds_loyalty_each_time():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    grist = _walker(engine, "Grist, the Hunger Tide", 3)
    _filler(engine, "Forest", "Basic Land — Forest", zone=Zone.LIBRARY)  # bottom
    _filler(engine, "Bug1", "Creature — Insect", power=1, toughness=1, zone=Zone.LIBRARY)
    _filler(engine, "Bug2", "Creature — Insect", power=1, toughness=1, zone=Zone.LIBRARY)  # top
    _loyalty(engine, grist, 1)
    insects = [o for o in _named(engine, "Insect") if o.is_token]
    assert len(insects) == 3  # one per pass: Bug2 milled, Bug1 milled, then the Forest ends the loop
    assert grist.counters["loyalty"] == 3 + 1 + 2 and len(p1.graveyard) == 3


def test_grist_milled_by_her_own_plus_one_counts_as_an_insect_card():
    engine = _game(library=0)
    grist = _walker(engine, "Grist, the Hunger Tide", 3)
    copy = _card(engine, "Grist, the Hunger Tide", zone=Zone.LIBRARY)  # a second Grist on top of the library
    _filler(engine, "Forest", "Basic Land — Forest", zone=Zone.LIBRARY)
    engine.state.player_by_id("p1").library.sort(key=lambda o: o is copy)  # the copy last = top
    _loyalty(engine, grist, 1)
    assert grist.counters["loyalty"] == 3 + 1 + 1


def test_grist_minus_two_sacrifices_a_creature_then_destroys_a_creature_or_planeswalker():
    engine = _game()
    grist = _walker(engine, "Grist, the Hunger Tide", 3)
    fodder = _filler(engine, "Fodder", "Creature — Bear", power=1, toughness=1)
    victim = _filler(engine, "Victim", "Creature — Bear", power=3, toughness=3, player="p2")
    _loyalty(engine, grist, -2)
    _answer(engine, pick=lambda c: str(fodder.instance_id) if any(str(o["id"]) == str(fodder.instance_id) for o in c["options"])
            else (str(victim.instance_id) if any(str(o["id"]) == str(victim.instance_id) for o in c["options"]) else None))
    assert fodder not in engine.state.battlefield and victim not in engine.state.battlefield


def test_grist_minus_five_drains_each_opponent_by_creature_cards_in_your_graveyard():
    engine = _game()
    grist = _walker(engine, "Grist, the Hunger Tide", 6)
    for i in range(3):
        _gy_filler(engine, "Creature — Bear", f"Dead{i}", power=1, toughness=1)
    _gy_filler(engine, "Sorcery", "Spell")
    life = engine.state.player_by_id("p2").life
    _loyalty(engine, grist, -5)
    assert engine.state.player_by_id("p2").life == life - 3


def test_inscription_of_abundance_unkicked_chooses_one_and_kicked_chooses_any_number():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    mine = _filler(engine, "Mine", "Creature — Bear", power=4, toughness=4)
    theirs = _filler(engine, "Theirs", "Creature — Bear", power=2, toughness=2, player="p2")
    spell = _card(engine, "Inscription of Abundance", zone=Zone.HAND)
    _cast(engine, spell, {"G": 2}, targets=[mine], groups=[[mine]], mode=0)
    assert mine.counters["+1/+1"] == 2
    with __import__("pytest").raises(ValueError):
        spell2 = _card(engine, "Inscription of Abundance", zone=Zone.HAND)
        _cast(engine, spell2, {"G": 2}, targets=[mine, mine], groups=[[mine], [mine]], mode=(0, 2))

    # Kicked: life gain (greatest power among *their* creatures) + fight, in one cast.
    spell3 = _card(engine, "Inscription of Abundance", zone=Zone.HAND)
    life = engine.state.player_by_id("p2").life
    _cast(engine, spell3, {"G": 5}, targets=[engine.state.player_by_id("p2"), mine, theirs],
          groups=[[engine.state.player_by_id("p2")], [mine], [theirs]], mode=(1, 2), kicked=1)
    assert engine.state.player_by_id("p2").life == life + 2  # their greatest power: 2 (the Bear fights afterwards)
    assert theirs not in engine.state.battlefield  # 6/6 (two counters) fights a 2/2


def test_into_the_pit_casts_the_top_card_only_by_sacrificing_a_nonland_permanent():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    pit = _card(engine, "Into the Pit")
    bolt = _filler(engine, "Bolt", "Instant", mv=1, zone=Zone.LIBRARY)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 1})
    engine.state.battlefield.remove(pit)  # nothing to sacrifice: not castable
    assert not engine.can_cast(p1, bolt)
    engine.state.battlefield.append(pit)
    fodder = _filler(engine, "Fodder", "Creature — Bear", power=1, toughness=1)
    assert engine.can_cast(p1, bolt)
    engine.cast_spell(p1, bolt, targets=None, target_groups=None)
    engine.resolve_until_stable()
    assert bolt.zone == Zone.GRAVEYARD
    assert sum(o.zone == Zone.GRAVEYARD for o in (pit, fodder)) == 1  # exactly one nonland permanent was sacrificed


def test_rendmaw_gives_every_player_a_tapped_goaded_bird_on_enter_and_on_multi_type_plays():
    engine = _game()
    _put_on_battlefield(engine, "Rendmaw, Creaking Nest")
    birds = [o for o in engine.state.battlefield if o.name == "Bird"]
    assert sorted(b.controller_id for b in birds) == ["p1", "p2"]
    assert all(b.tapped and (b.power, b.toughness) == (2, 2) and b.goaded_permanently for b in birds)

    # An Artifact Creature spell has two card types → another round of Birds; a plain creature does not.
    plain = _filler(engine, "Plain", "Creature — Bear", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, plain, {"C": 1})
    assert len([o for o in engine.state.battlefield if o.name == "Bird"]) == 2
    both = _filler(engine, "Golem", "Artifact Creature — Golem", power=1, toughness=1, zone=Zone.HAND)
    _cast(engine, both, {"C": 1})
    assert len([o for o in engine.state.battlefield if o.name == "Bird"]) == 4


def test_titania_lets_you_play_forests_from_the_graveyard_and_each_forest_makes_a_5_3():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Titania, Nature's Force")
    forest = _gy_filler(engine, "Basic Land — Forest", "Forest")
    mountain = _gy_filler(engine, "Basic Land — Mountain", "Mountain")
    engine.state.current_step = "main1"
    assert engine.can_play_land(p1, forest) and not engine.can_play_land(p1, mountain)
    engine.play_land(p1, forest)
    engine.resolve_until_stable()
    assert forest in engine.state.battlefield
    elementals = [o for o in _named(engine, "Elemental") if o.is_token]
    assert len(elementals) == 1 and (elementals[0].power, elementals[0].toughness) == (5, 3)


def test_titania_optionally_mills_three_when_an_elemental_dies():
    engine = _game(library=10)
    p1 = engine.state.player_by_id("p1")
    _card(engine, "Titania, Nature's Force")
    elemental = _filler(engine, "Elemental", "Creature — Elemental", power=1, toughness=1)
    engine.rules.destroy(elemental)
    engine.resolve_until_stable()
    engine.resolve_pending_choice("do")  # the trigger's "you may"
    engine.resolve_until_stable()
    assert len(p1.graveyard) == 1 + 3


def test_ursine_monstrosity_mills_forces_an_attack_and_grows_by_graveyard_card_types():
    engine = _game(players=3, library=10)
    p1 = engine.state.player_by_id("p1")
    bear = _card(engine, "Ursine Monstrosity")
    _gy_filler(engine, "Sorcery", "S")
    _gy_filler(engine, "Land", "L")
    _step(engine, "begin_combat")
    engine.recompute_continuous_effects()
    assert bear.must_attack_player_id in ("p2", "p3")
    # Graveyard: Sorcery + Land + the milled Forest (Land) = 2 types → 3/3 + 2/+2, indestructible.
    assert (bear.power, bear.toughness) == (5, 5)
    assert "indestructible" in bear.granted_keywords


def test_vile_mutilator_makes_each_opponent_sacrifice_a_nontoken_enchantment_then_creature():
    engine = _game()
    mutilator = _card(engine, "Vile Mutilator", zone=Zone.HAND)
    fodder = _filler(engine, "Fodder", "Creature — Bear", power=1, toughness=1)
    ench = _filler(engine, "Aura", "Enchantment", player="p2")
    token = _filler(engine, "Token Bear", "Token Creature — Bear", power=1, toughness=1, player="p2")
    bear = _filler(engine, "Their Bear", "Creature — Bear", power=2, toughness=2, player="p2")
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, mutilator, targets=None, target_groups=None, sacrifice_choice=fodder.instance_id)
    engine.resolve_until_stable()
    _answer(engine)
    assert fodder not in engine.state.battlefield  # the additional cost
    assert ench not in engine.state.battlefield and bear not in engine.state.battlefield
    assert token in engine.state.battlefield  # tokens are not "nontoken" creatures


def test_whip_of_erebos_reanimates_with_haste_exiles_at_end_step_and_never_to_the_graveyard():
    engine = _game()
    whip = _card(engine, "Whip of Erebos")
    dead = _gy_filler(engine, "Creature — Bear", "Dead", power=2, toughness=2)
    ally = _filler(engine, "Ally", "Creature — Bear", power=1, toughness=1)
    engine.recompute_continuous_effects()
    assert "lifelink" in ally.granted_keywords
    p1 = engine.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 2, "C": 2})
    _activate(engine, whip, 0, targets=[dead])
    assert dead in engine.state.battlefield and "haste" in dead.granted_keywords
    engine.rules.destroy(dead)  # "if it would leave the battlefield, exile it instead"
    engine.resolve_until_stable()
    assert dead.zone == Zone.EXILE

    dead2 = _gy_filler(engine, "Creature — Bear", "Dead2", power=2, toughness=2)
    whip.tapped = False
    p1.mana_pool.add_many({"B": 2, "C": 2})
    _activate(engine, whip, 0, targets=[dead2])
    assert dead2 in engine.state.battlefield
    engine._fire_delayed_triggers("end")  # the next end step's beginning
    engine.resolve_until_stable()
    assert dead2.zone == Zone.EXILE


def test_old_stickfingers_reveals_until_x_creatures_into_the_graveyard_and_sizes_itself_by_them():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    # library (bottom → top): Forest, Bear, Island, Bear, Bear  → X=2 reveals Bear, Bear (stops after the 2nd creature)
    _filler(engine, "Forest", "Basic Land — Forest", zone=Zone.LIBRARY)
    for n, tl in (("Bear1", "Creature — Bear"), ("Island", "Basic Land — Island"), ("Bear2", "Creature — Bear"), ("Bear3", "Creature — Bear")):
        _filler(engine, n, tl, power=1 if "Creature" in tl else None, toughness=1 if "Creature" in tl else None, zone=Zone.LIBRARY)
    stick = _card(engine, "Old Stickfingers", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"B": 1, "G": 1, "C": 2})
    engine.cast_spell(p1, stick, targets=None, target_groups=None, x=2)
    engine.resolve_until_stable()
    assert sorted(o.name for o in p1.graveyard) == ["Bear2", "Bear3"]
    assert stick in engine.state.battlefield
    engine.recompute_continuous_effects()
    assert (stick.power, stick.toughness) == (2, 2)
    assert len(p1.library) == 3  # Forest, Bear1, Island untouched or back on the bottom


def _winter_end_step(engine, picks):
    """Fire Winter's end-step trigger and select ``picks`` (graveyard cards), then finish the selection."""
    _step(engine, "end")
    for card in picks:
        engine.resolve_pending_choice(str(card.instance_id))
    if engine.state.pending_choice and engine.state.pending_choice["options"][-1]["id"] == "decline":
        engine.resolve_pending_choice("decline")


def test_winter_exiles_a_four_type_set_and_returns_a_permanent_with_a_finality_counter():
    engine = _game()
    winter = _card(engine, "Winter, Cynical Opportunist")
    land = _gy_filler(engine, "Basic Land — Forest", "L")
    spell = _gy_filler(engine, "Instant", "I")
    sorcery = _gy_filler(engine, "Sorcery", "S")
    creature = _gy_filler(engine, "Creature — Elf", "C", power=1, toughness=1)
    extra = _gy_filler(engine, "Sorcery", "Extra")
    _winter_end_step(engine, [land, spell, sorcery, creature])
    # choose which permanent returns (only the land and the creature are permanent cards)
    assert engine.state.pending_choice and engine.state.pending_choice["kind"] == "choose_objects"
    engine.resolve_pending_choice(str(creature.instance_id))
    assert creature in engine.state.battlefield and creature.counters.get("finality") == 1
    assert all(o.zone == Zone.EXILE for o in (land, spell, sorcery)) and extra.zone == Zone.GRAVEYARD
    engine.rules.destroy(creature)  # RULE 122.1h: exiled instead of going to the graveyard
    engine.resolve_until_stable()
    assert creature.zone == Zone.EXILE


def test_winter_does_nothing_for_a_set_with_fewer_than_four_card_types():
    engine = _game()
    _card(engine, "Winter, Cynical Opportunist")
    a = _gy_filler(engine, "Instant", "I")
    b = _gy_filler(engine, "Sorcery", "S")
    _winter_end_step(engine, [a, b])
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.GRAVEYARD and engine.state.pending_choice is None


def test_wrenn_and_seven_plus_one_puts_revealed_lands_in_hand_and_the_rest_in_the_graveyard():
    engine = _game(library=0)
    p1 = engine.state.player_by_id("p1")
    wrenn = _walker(engine, "Wrenn and Seven", 5)
    spell = _filler(engine, "Spell", "Sorcery", zone=Zone.LIBRARY)
    lands = [_filler(engine, f"L{i}", "Basic Land — Forest", zone=Zone.LIBRARY) for i in range(3)]
    _loyalty(engine, wrenn, 1)
    _answer(engine)
    assert sorted(o.name for o in p1.hand) == ["L0", "L1", "L2"] and spell in p1.graveyard


def test_wrenn_and_seven_zero_puts_any_number_of_lands_tapped_onto_the_battlefield():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    wrenn = _walker(engine, "Wrenn and Seven", 5)
    lands = [_filler(engine, f"L{i}", "Basic Land — Forest", zone=Zone.HAND) for i in range(2)]
    keep = _filler(engine, "Spell", "Sorcery", zone=Zone.HAND)
    _loyalty(engine, wrenn, 0)
    _answer(engine)
    assert all(l in engine.state.battlefield and l.tapped for l in lands) and keep in p1.hand


def test_wrenn_and_seven_minus_three_makes_a_treefolk_that_scales_with_lands():
    engine = _game()
    wrenn = _walker(engine, "Wrenn and Seven", 5)
    for i in range(3):
        _filler(engine, f"L{i}", "Basic Land — Forest")
    _loyalty(engine, wrenn, -3)
    treefolk = [o for o in _named(engine, "Treefolk") if o.is_token][0]
    engine.recompute_continuous_effects()
    assert combat.has(treefolk, "reach") and (treefolk.power, treefolk.toughness) == (3, 3)


def test_wrenn_and_seven_minus_eight_returns_every_permanent_card_and_removes_the_hand_size_limit():
    engine = _game()
    p1 = engine.state.player_by_id("p1")
    wrenn = _walker(engine, "Wrenn and Seven", 8)
    bear = _gy_filler(engine, "Creature — Bear", "Bear", power=1, toughness=1)
    land = _gy_filler(engine, "Land", "Land")
    spell = _gy_filler(engine, "Sorcery", "Spell")
    _loyalty(engine, wrenn, -8)
    assert bear in p1.hand and land in p1.hand and spell in p1.graveyard
    assert len(p1.emblems) == 1
