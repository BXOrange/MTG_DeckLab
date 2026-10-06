"""Gameplay regressions for the Turtle Power! (Teenage Mutant Ninja Turtles Commander) deck batch."""
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import (
    RICH, activate, answer, attack, card, cast, enter, filler, game, main_phase, named, pick_label, put_on_battlefield,
    stack_library, step,
)


def _yes(choice):
    return next((str(o["id"]) for o in choice.get("options", []) if o.get("id") in ("yes", "do")), None)


def test_big_mother_mouser_doubles_on_attack_and_leaves_robots_equal_to_its_counters():
    engine = game()
    mouser = card(engine, "Big Mother Mouser", zone=Zone.HAND)
    cast(engine, mouser)
    assert mouser.counters.get("+1/+1") == 2
    mouser.summoning_sick = False
    attack(engine, [mouser])
    assert mouser.counters.get("+1/+1") == 4
    engine.rules.put_into_graveyard(mouser)
    engine.resolve_until_stable()
    robots = named(engine, "Robot")
    assert len(robots) == 4 and all(r.is_token and r.card.is_artifact for r in robots)


def test_casey_jones_pings_an_opponent_for_counters_put_on_your_creatures():
    engine = game()
    card(engine, "Casey Jones, Back Alley Brute")
    ally = filler(engine, "Ally", power=1, toughness=1)
    engine.rules.add_counters(ally, 3, "+1/+1", source=ally)
    engine.resolve_until_stable()
    answer(engine)
    assert engine.state.player_by_id("p2").life == 17


def test_bebop_draws_and_loses_life_equal_to_his_counters():
    engine = game()
    bebop = card(engine, "Bebop, Skull & Crossbones")
    bebop.add_counters("+1/+1", 2)
    me = engine.state.player_by_id("p1")
    hand, life = len(me.hand), me.life
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=bebop.instance_id, source_controller_id="p1",
                                      target_id="p2", is_player=True, combat=True, amount=2))
    engine.resolve_until_stable()
    answer(engine, _yes)
    assert len(me.hand) == hand + 2 and me.life == life - 2


def test_april_investigates_for_mutants_ninjas_and_turtles():
    engine = game()
    card(engine, "April O'Neil, Live on the Scene")
    turtle = filler(engine, "Leo", type_line="Creature — Mutant Ninja Turtle", power=2, toughness=2, zone=Zone.HAND)
    human = filler(engine, "Human", type_line="Creature — Human", power=1, toughness=1, zone=Zone.HAND)
    for c in (turtle, human):
        engine.state.player_by_id("p1").hand[:] = [o for o in engine.state.player_by_id("p1").hand if o is not c]
        c.zone = Zone.BATTLEFIELD
        engine.state.add_to_battlefield(c)
        enter(engine, c)
    assert len(named(engine, "Clue")) == 1


def test_heroes_in_a_half_shell_grows_the_connecting_team_and_draws():
    engine = game()
    heroes = card(engine, "Heroes in a Half Shell")
    ninja = filler(engine, "Ninja", type_line="Creature — Human Ninja", power=2, toughness=2)
    human = filler(engine, "Human", type_line="Creature — Human", power=2, toughness=2)
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    heroes.summoning_sick = False
    attack(engine, [heroes, ninja, human])
    engine.state.current_step = "combat_damage"
    engine._apply_combat_damage([(engine.state.player_by_id("p2"), c.power, c) for c in (heroes, ninja, human)])
    engine.resolve_until_stable()
    assert heroes.counters.get("+1/+1") == 1 and ninja.counters.get("+1/+1") == 1 and not human.counters.get("+1/+1")
    assert len(me.hand) == hand + 1


def test_coin_of_mastery_counts_actual_artifact_mana_including_artifact_creatures():
    engine = game()
    card(engine, "Coin of Mastery")
    me = engine.state.player_by_id("p1")
    rock = card(engine, "Sol Ring")
    creature_rock = filler(engine, "Creature Rock", type_line="Artifact Creature", power=1, toughness=1,
                           oracle_text="{T}: Add {G}.")
    engine.tap_for_mana(me, rock)
    engine.tap_for_mana(me, creature_rock)
    cub = filler(engine, "Cub", power=1, toughness=1, mv=3, zone=Zone.HAND)
    cast(engine, cub, pool={})
    assert cub.counters.get("+1/+1") == 3
    assert cub.mana_spent_to_cast_artifact == 3 and cub.mana_spent_to_cast_creature == 1


def test_dimension_x_pizzasaur_buffs_then_destroys_a_creature_up_to_the_counter_total():
    engine = game()
    victim = filler(engine, "Victim", power=1, toughness=1, mv=2, player="p2")
    big = filler(engine, "Big", power=5, toughness=5, mv=7, player="p2")
    ally = filler(engine, "Ally", power=1, toughness=1)
    pizza = card(engine, "Dimension X Pizzasaur", zone=Zone.HAND)
    cast(engine, pizza)
    engine.resolve_pending_choice(pick_label("Ally")(engine.state.pending_choice))
    answer(engine, pick_label("Victim"))
    assert ally.counters.get("+1/+1") == 2 and victim.zone == Zone.GRAVEYARD and big.zone == Zone.BATTLEFIELD


def test_high_score_adds_a_counter_and_draws_for_the_biggest_creature():
    engine = game()
    card(engine, "High Score")
    ally = filler(engine, "Ally", power=4, toughness=4)
    filler(engine, "Their Small", power=2, toughness=2, player="p2")
    engine.rules.add_counters(ally, 1, "+1/+1", source=ally)
    assert ally.counters.get("+1/+1") == 2
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    step(engine, "end")
    assert len(me.hand) == hand + 1


def test_everything_pizza_fetches_a_land_and_unloads_all_its_effects():
    engine = game()
    pizza = card(engine, "Everything Pizza", zone=Zone.HAND)
    cast(engine, pizza)
    answer(engine)
    me = engine.state.player_by_id("p1")
    hand = len(me.hand)
    them = engine.state.player_by_id("p2")
    them_hand = len(them.hand)
    filler(engine, "Their Card", zone=Zone.HAND, player="p2")
    ally = filler(engine, "Ally", power=1, toughness=1)
    me.mana_pool.add_many({"W": 1, "U": 1, "B": 1, "R": 1, "G": 1, "C": 2})
    life = me.life
    activate(engine, pizza, 0, targets=[me, them, ally])
    assert me.life == life + 3 and len(me.hand) == hand + 1
    answer(engine)  # the opponent's discard
    assert them.life == 17 and ally.counters.get("+1/+1") == 3
    assert len(them.hand) == them_hand  # the card added above was discarded


def test_continue_only_targets_cards_in_the_current_death_incarnation():
    from mtg_analyzer.game.targeting import legal_targets
    engine = game()
    died = filler(engine, 'Died', power=2, toughness=2)
    engine.rules.put_into_graveyard(died)
    milled = filler(engine, 'Milled', zone=Zone.GRAVEYARD, power=2, toughness=2)
    spell = card(engine, 'Continue?', zone=Zone.HAND)
    spec = spell.spell_effects[0].target_spec
    assert [o['instance_id'] for o in legal_targets(engine.state, "p1", spec, spell)] == [died.instance_id]
    cast(engine, spell, targets=[died])
    assert died.zone == Zone.BATTLEFIELD and milled.zone == Zone.GRAVEYARD


def test_double_jump_grants_flying_and_sets_base_size_until_cleanup():
    engine = game()
    ally = filler(engine, 'Ally', power=1, toughness=1)
    ally.add_counters('+1/+1', 2)
    cast(engine, card(engine, 'Double Jump // Flying Kick', zone=Zone.HAND), targets=[ally])
    assert combat.has(ally, 'flying') and ally.power == 7
    engine._step_cleanup()
    assert ally.power == 3 and combat.has(ally, 'flying')


def test_fast_forward_counts_distinct_attacked_opponents_and_goads():
    engine = game(players=3)
    attackers = [filler(engine, f'Attacker {i}', power=1, toughness=1) for i in range(2)]
    victim = filler(engine, 'Victim', player='p2', power=1, toughness=1)
    attack(engine, attackers)
    spell = card(engine, 'Fast Forward', zone=Zone.HAND)
    assert continuous.self_cost_reduction_for(spell, engine.state)[0] == 1
    cast(engine, spell)
    assert combat.is_goaded(victim)


def test_game_over_discount_requires_half_starting_life_and_clears_creatures():
    engine = game()
    creature = filler(engine, 'Victim', power=2, toughness=2)
    spell = card(engine, 'Game Over', zone=Zone.HAND)
    assert continuous.self_cost_reduction_for(spell, engine.state)[0] == 0
    engine.state.player_by_id('p2').life = 10
    assert continuous.self_cost_reduction_for(spell, engine.state)[0] == 2
    cast(engine, spell)
    assert creature.zone == Zone.GRAVEYARD


def test_new_hero_draws_for_the_target_player_and_copies_with_x_cap():
    from mtg_analyzer.game.targeting import legal_targets
    engine = game()
    ally = filler(engine, 'Ally', power=2, toughness=2, mv=2)
    large = filler(engine, 'Large', power=2, toughness=2, mv=5)
    spell = card(engine, 'Here Comes a New Hero!', zone=Zone.HAND)
    spell.x_paid = 2
    options = legal_targets(engine.state, "p1", spell.spell_effects[1].target_spec, spell)
    assert ally.instance_id in [o['instance_id'] for o in options] and large.instance_id not in [o['instance_id'] for o in options]
    them = engine.state.player_by_id('p2')
    cast(engine, spell, targets=[them, ally], x=2)
    assert len(them.hand) == 2 and len(named(engine, 'Ally')) == 2


def test_hidden_hideout_lifelink_requires_a_counter():
    from mtg_analyzer.game.targeting import legal_targets
    engine = game()
    hideout = card(engine, 'Hidden Hideout')
    ally = filler(engine, 'Ally', power=1, toughness=1)
    assert not legal_targets(engine.state, "p1", hideout.activated_abilities[0].effects[0].target_spec, hideout)
    ally.add_counters('flying', 1)
    engine.state.player_by_id('p1').mana_pool.add_many({'C': 2})
    activate(engine, hideout, targets=[ally])
    assert combat.has(ally, 'lifelink')


def test_irma_keeps_her_name_and_trigger_after_copying():
    engine = game()
    irma = card(engine, 'Irma, Part-Time Mutant')
    ally = filler(engine, 'Ally', power=3, toughness=3)
    step(engine, 'begin_combat')
    answer(engine, pick_label('Ally'))
    assert irma.name == 'Irma, Part-Time Mutant' and irma.power == 4 and irma.triggered_abilities


def test_level_up_granted_trigger_doubles_then_checks_power():
    engine = game()
    ally = filler(engine, 'Ally', power=2, toughness=2)
    aura = card(engine, 'Level Up', zone=Zone.HAND)
    cast(engine, aura, targets=[ally])
    assert ally.counters.get('+1/+1') == 1
    ally.add_counters('+1/+1', 3)
    me = engine.state.player_by_id('p1')
    attack(engine, [ally])
    assert ally.counters.get('+1/+1') == 8 and len(me.hand) == 1


def test_lita_exhausts_each_mode_once_per_turn():
    engine = game()
    lita = card(engine, 'Lita, Little Orphan Amphibian')
    for i in range(4):
        put_on_battlefield(engine, 'Memnite')
        answer(engine)
    assert lita.counters.get('+1/+1') == 1 and len(named(engine, 'Food')) == 1


def test_michelangelo_checks_raid_in_second_main():
    engine = game()
    mike = card(engine, 'Michelangelo, the Heart')
    step(engine, 'main2')
    assert not named(engine, 'Food')
    ally = filler(engine, "Ally", power=2, toughness=2)
    attack(engine, [mike])
    step(engine, 'main2')
    answer(engine, pick_label('Ally'))
    assert ally.counters.get('+1/+1') == 1 and len(named(engine, 'Food')) == 1


def test_mole_module_only_offers_permanents_from_its_mill():
    engine = game()
    module = card(engine, 'Mole Module')
    permanent = filler(engine, 'Milled Land', type_line='Land', zone=Zone.LIBRARY)
    stack_library(engine, 'p1', permanent)
    unrelated = filler(engine, 'Old Land', type_line='Land', zone=Zone.GRAVEYARD)
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=module.instance_id, source_controller_id='p1',
                                      target_id='p2', is_player=True, combat=True, amount=2))
    engine.resolve_until_stable()
    answer(engine, pick_label('Milled Land'))
    assert permanent.zone == Zone.BATTLEFIELD and unrelated.zone == Zone.GRAVEYARD


def test_ninja_pizza_grants_foods_mana_and_creates_food_in_main2():
    engine = game()
    card(engine, 'Ninja Pizza')
    step(engine, 'main2')
    food = named(engine, 'Food')[0]
    me = engine.state.player_by_id('p1')
    engine.tap_for_mana(me, food)
    assert food.zone == Zone.GRAVEYARD and sum(me.mana_pool.pool.values()) == 1


def test_raphael_only_doubles_damage_from_counter_bearing_creatures():
    engine = game()
    raph = card(engine, 'Raphael, the Muscle', zone=Zone.HAND)
    cast(engine, raph)
    assert len(named(engine, 'Mutagen')) == 1
    ally = filler(engine, 'Ally', power=1, toughness=1)
    them = engine.state.player_by_id('p2')
    engine.rules.deal_damage(them, 2, ally)
    ally.add_counters('flying', 1)
    engine.rules.deal_damage(them, 2, ally)
    assert them.life == 14


def test_foot_chopper_creates_equips_and_sacrifices_the_damage_dealer():
    engine = game()
    chopper = card(engine, 'Foot Chopper', zone=Zone.HAND)
    cast(engine, chopper)
    ninja = named(engine, 'Ninja')[0]
    assert chopper.attached_to == ninja.instance_id and combat.has(ninja, 'flying')
    ninja.add_counters('+1/+1', 2)
    me = engine.state.player_by_id('p1')
    hand = len(me.hand)
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=ninja.instance_id, source_controller_id='p1',
                                      target_id='p2', is_player=True, combat=True, amount=3))
    engine.resolve_until_stable()
    answer(engine, pick_label('Ninja'))
    assert ninja.zone == Zone.GRAVEYARD and len(me.hand) == hand + 3


def test_shredder_copies_attack_other_opponents_and_halves_damaged_player_life():
    engine = game(players=3)
    shredder = card(engine, 'Shredder, Shadow Master')
    attack(engine, [shredder], defender={'kind': 'player', 'id': 'p2'})
    copies = [o for o in named(engine, shredder.name) if o.is_token]
    assert len(copies) == 1 and copies[0].combat_defender == {'kind': 'player', 'id': 'p3'}
    assert not copies[0].card.is_legendary
    engine.state.fire_event(GameEvent(EventType.DAMAGE, source_id=shredder.instance_id, source_controller_id='p1',
                                      target_id='p2', is_player=True, combat=True, amount=1))
    engine.resolve_until_stable()
    assert engine.state.player_by_id('p2').life == 10
    step(engine, 'end_combat')
    assert copies[0].zone == Zone.GRAVEYARD


def test_shellshock_earns_tokens_for_damage_to_each_opponents_target():
    engine = game(players=3)
    victims = [filler(engine, f'Victim {i}', player=f'p{i}', power=3, toughness=3) for i in (2, 3)]
    cast(engine, card(engine, 'Shellshock', zone=Zone.HAND), targets=victims, x=1)
    assert all(o.damage_marked == 1 for o in victims) and len(named(engine, 'Mutagen')) == 2


def test_special_move_uses_the_chosen_modes_and_sacrifices_the_dealer():
    engine = game()
    artifact = filler(engine, 'Artifact', type_line='Artifact', player='p2')
    dealer = filler(engine, 'Dealer', power=3, toughness=3)
    them = engine.state.player_by_id('p2')
    cast(engine, card(engine, 'Special Move', zone=Zone.HAND), mode=[0, 2], targets=[artifact, dealer, them])
    assert artifact.zone == Zone.GRAVEYARD and dealer.zone == Zone.GRAVEYARD and them.life == 17


def test_swift_demise_destroys_creatures_damaged_even_after_damage_is_removed():
    engine = game()
    prior = filler(engine, 'Prior', player='p2', power=2, toughness=2)
    engine.rules.deal_damage(prior, 1)
    prior.damage_marked = 0
    victim = filler(engine, 'Victim', player='p2', power=2, toughness=2)
    untouched = filler(engine, 'Untouched', player='p2', power=2, toughness=2)
    cast(engine, card(engine, 'Swift Demise', zone=Zone.HAND), targets=[victim])
    assert prior.zone == victim.zone == Zone.GRAVEYARD and untouched.zone == Zone.BATTLEFIELD


def test_fused_double_jump_resolves_both_halves_in_order():
    engine = game()
    ally = filler(engine, 'Ally', power=1, toughness=1)
    victim = filler(engine, 'Victim', power=1, toughness=5, player='p2')
    cast(engine, card(engine, 'Double Jump // Flying Kick', zone=Zone.HAND), face='fuse', targets=[ally, ally, victim])
    assert combat.has(ally, 'flying') and ally.power == 5 and victim.zone == Zone.GRAVEYARD


def test_pizzasaur_does_not_offer_a_target_above_the_counter_total():
    engine = game()
    filler(engine, 'Small', power=1, toughness=1, mv=2, player='p2')
    filler(engine, 'Large', power=1, toughness=1, mv=7, player='p2')
    ally = filler(engine, 'Ally', power=1, toughness=1)
    cast(engine, card(engine, 'Dimension X Pizzasaur', zone=Zone.HAND))
    engine.resolve_pending_choice(pick_label('Ally')(engine.state.pending_choice))
    choice = engine.state.pending_choice
    assert any('Small' in o['label'] for o in choice['options'])
    assert not any('Large' in o['label'] for o in choice['options'])


def test_artifact_creature_mana_still_pays_a_creature_source_only_spell():
    engine = game()
    me = engine.state.player_by_id("p1")
    rock = filler(engine, "Creature Rock", type_line="Artifact Creature", power=1, toughness=1,
                  oracle_text="{T}: Add {C}{C}.")
    engine.tap_for_mana(me, rock)
    superion = card(engine, "Myr Superion", zone=Zone.HAND)
    cast(engine, superion, pool={})
    assert superion.zone == Zone.BATTLEFIELD and me.mana_pool.total() == 0


def test_irma_does_not_accumulate_abilities_from_previous_copies():
    engine = game()
    irma = card(engine, 'Irma, Part-Time Mutant')
    visionary = card(engine, 'Elvish Visionary')
    plain = filler(engine, 'Plain', power=2, toughness=2)
    step(engine, 'begin_combat')
    answer(engine, pick_label('Elvish Visionary'))
    assert len(irma.triggered_abilities) == 2
    step(engine, 'begin_combat')
    answer(engine, pick_label('Plain'))
    assert len(irma.triggered_abilities) == 1 and irma.name == 'Irma, Part-Time Mutant'


def test_shellshock_does_not_create_mutagen_for_prevented_damage():
    engine = game()
    victim = filler(engine, 'Shielded', player='p2', power=3, toughness=3)
    victim.add_counters('shield', 1)
    cast(engine, card(engine, 'Shellshock', zone=Zone.HAND), targets=[victim], x=1)
    assert victim.damage_marked == 0 and not victim.counters.get('shield')
    assert not named(engine, 'Mutagen')


def test_continue_does_not_target_a_card_that_left_the_graveyard_and_was_discarded():
    from mtg_analyzer.game.targeting import legal_targets
    engine = game()
    died = filler(engine, 'Died', power=2, toughness=2)
    engine.rules.put_into_graveyard(died)
    engine.rules.return_to_hand(died)
    engine.rules.discard(engine.state.player_by_id('p1'), 1)
    spell = card(engine, 'Continue?', zone=Zone.HAND)
    assert not legal_targets(engine.state, 'p1', spell.spell_effects[0].target_spec, spell)


def test_special_move_does_not_sacrifice_the_recipient_when_its_dealer_becomes_illegal():
    engine = game()
    me = engine.state.player_by_id('p1')
    artifact = filler(engine, 'Artifact', type_line='Artifact', player='p2')
    dealer = filler(engine, 'Dealer', power=3, toughness=3)
    recipient = filler(engine, 'Recipient', power=2, toughness=4)
    spell = card(engine, 'Special Move', zone=Zone.HAND)
    main_phase(engine)
    me.mana_pool.add_many(RICH)
    engine.cast_spell(me, spell, mode=[0, 2], targets=[artifact, dealer, recipient])
    engine.rules.return_to_hand(dealer)
    engine.resolve_until_stable()
    assert artifact.zone == Zone.GRAVEYARD
    assert recipient.zone == Zone.BATTLEFIELD and recipient.damage_marked == 0
