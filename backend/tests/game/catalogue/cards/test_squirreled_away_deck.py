"""Behavior of the Squirreled Away Commander deck's authored abilities."""
from mtg_analyzer.models.game.events import GameEvent, EventType
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object


def game(name, opponents=1):
    engine = GameEngine.new_game(
        [('p1', 'A', [])] + [(f'p{i+2}', 'B', []) for i in range(opponents)],
        starting_hand=0, starting_life=20,
    )
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id='p1', zone=Zone.BATTLEFIELD)
    obj.controller_id = 'p1'
    bind_from_catalogue(obj)
    obj.summoning_sick = False
    engine.state.add_to_battlefield(obj)
    engine.state.current_step = 'main1'
    return engine, engine.state.players[0], obj


def test_chittering_witch_creates_one_rat_per_opponent_on_entry():
    engine, player, witch = game('Chittering Witch', opponents=3)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=witch.instance_id, controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token and o.name == 'Rat']) == 3


def test_chitterspitter_scales_only_own_squirrels_with_acorns():
    engine, player, spitter = game('Chitterspitter')
    squirrel = battlefield_object(engine, 'p1', 'Squirrel', 'Creature — Squirrel', is_creature=True, power=1, toughness=1)
    bear = battlefield_object(engine, 'p1', 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    enemy = battlefield_object(engine, 'p2', 'Enemy', 'Creature — Squirrel', is_creature=True, power=1, toughness=1)
    spitter.counters['acorn'] = 3
    engine.recompute_continuous_effects()
    assert (squirrel.power, squirrel.toughness) == (4, 4)
    assert bear.power == 2 and enemy.power == 1
    spitter.counters.clear()
    engine.recompute_continuous_effects()
    assert squirrel.power == 1


def test_nested_shambler_uses_power_at_death_and_creates_tapped_tokens():
    engine, player, shambler = game('Nested Shambler')
    shambler.counters['+1/+1'] = 2
    engine.recompute_continuous_effects()
    engine.rules.destroy(shambler)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    squirrels = [o for o in engine.state.battlefield if o.is_token]
    assert len(squirrels) == 3
    assert all(o.tapped and o.power == 1 for o in squirrels)


def test_swarmyard_regenerates_a_squirrel():
    engine, player, yard = game('Swarmyard')
    squirrel = battlefield_object(engine, 'p1', 'Squirrel', 'Creature — Squirrel', is_creature=True, power=1, toughness=1)
    engine.activate_ability(player, yard, 0, targets=[squirrel])
    engine.resolve_until_stable()
    engine.rules.destroy(squirrel)
    assert squirrel in engine.state.battlefield and squirrel.tapped


def test_odd_acorn_gang_grants_tap_pump_to_squirrels():
    engine, player, gang = game('The Odd Acorn Gang')
    squirrel = battlefield_object(engine, 'p1', 'Squirrel', 'Creature — Squirrel', is_creature=True, power=1, toughness=1)
    squirrel.summoning_sick = False
    engine.recompute_continuous_effects()
    engine.activate_ability(player, squirrel, 0, targets=[gang])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert squirrel.tapped and gang.power == gang.card.power + 2


def test_hazel_copies_a_squirrel_twice_at_own_end_step():
    from mtg_analyzer.models.cards.card import Card
    engine, player, hazel = game('Hazel of the Rootbloom')
    squirrel = engine.rules.create_token('p1', Card(id='sq', name='Squirrel', type_line='Token Creature — Squirrel', is_creature=True, power=1, toughness=1))[0]
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step='end', player_id='p1'))
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice(str(squirrel.instance_id))
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token]) == 3


def test_brewmaster_tracks_exile_and_food_borrows_the_creatures_ability():
    engine, player, brew = game("Hazel's Brewmaster")
    donor = GameObject(CardDatabase(DB_PATH).get_card('Llanowar Elves'), owner_id='p1', zone=Zone.GRAVEYARD)
    bind_from_catalogue(donor)
    player.graveyard.append(donor)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=brew.instance_id, controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.resolve_pending_choice(str(donor.instance_id))
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert donor.instance_id in brew.exiled_with_ids
    assert any(o.name == 'Food' for o in engine.state.battlefield)


def test_gourmands_talent_grants_food_type_and_activation_only_during_your_turn():
    from mtg_analyzer.game.continuous import has_subtype
    engine, player, talent = game("Gourmand's Talent")
    rock = battlefield_object(engine, 'p1', 'Rock', 'Artifact')
    engine.recompute_continuous_effects()
    assert has_subtype(rock, 'Food')
    player.mana_pool.add_many({'C': 2})
    engine.activate_ability(player, rock, 0)
    engine.resolve_until_stable()
    assert rock not in engine.state.battlefield and player.life == 23
    rock2 = battlefield_object(engine, 'p1', 'Rock2', 'Artifact')
    engine.state.active_player_index = 1
    engine.recompute_continuous_effects()
    assert not has_subtype(rock2, 'Food') and not rock2._granted_activated_abilities


def test_garruks_wolf_death_adds_loyalty_to_each_garruk():
    engine, player, garruk = game('Garruk, Cursed Huntsman')
    garruk.counters['loyalty'] = 5
    index = next(i for i,a in enumerate(garruk.activated_abilities) if a.cost.loyalty == 0)
    engine.activate_ability(player, garruk, index)
    engine.resolve_until_stable()
    wolves = [o for o in engine.state.battlefield if o.is_token]
    assert len(wolves) == 2
    engine.rules.destroy(wolves[0])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert garruk.counters['loyalty'] == 6


def cast(engine, player, name, targets=()):
    spell = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({'B': 10, 'G': 10, 'C': 10})
    engine.cast_spell(player, spell, targets=list(targets))
    engine.resolve_until_stable()


def test_maelstrom_pulse_destroys_same_name_on_both_sides():
    engine, player, _ = game('Chitterspitter')
    a = battlefield_object(engine, 'p1', 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    b = battlefield_object(engine, 'p2', 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    other = battlefield_object(engine, 'p2', 'Other', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    cast(engine, player, 'Maelstrom Pulse', [a])
    assert a not in engine.state.battlefield and b not in engine.state.battlefield
    assert other in engine.state.battlefield


def test_saw_in_half_uses_live_stats_and_the_victims_controller():
    engine, player, _ = game('Chitterspitter')
    victim = battlefield_object(engine, 'p2', 'Victim', 'Creature — Bear', is_creature=True, power=3, toughness=5)
    victim.counters['+1/+1'] = 2
    engine.recompute_continuous_effects()
    cast(engine, player, 'Saw in Half', [victim])
    copies = [o for o in engine.state.battlefield if o.is_token]
    assert len(copies) == 2
    assert all(o.controller_id == 'p2' and (o.power, o.toughness) == (3, 4) for o in copies)


def test_saw_in_half_creates_no_copies_when_destruction_is_regenerated():
    engine, player, _ = game('Chitterspitter')
    victim = battlefield_object(engine, 'p2', 'Victim', 'Creature — Bear', is_creature=True, power=3, toughness=5)
    engine.rules.regenerate(victim)
    cast(engine, player, 'Saw in Half', [victim])
    assert victim in engine.state.battlefield and not any(o.is_token for o in engine.state.battlefield)


def test_plaguecrafter_sacrifices_a_permanent_or_discards_when_there_is_none():
    engine, player, plague = game('Plaguecrafter')
    opponent = engine.state.players[1]
    handcard = GameObject(CardDatabase(DB_PATH).get_card('Forest'), owner_id='p2', zone=Zone.HAND)
    opponent.hand.append(handcard)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=plague.instance_id, controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        options = engine.state.pending_choice['options']
        engine.resolve_pending_choice(options[0]['id'])
        engine.resolve_until_stable()
    assert plague not in engine.state.battlefield
    assert not opponent.hand and handcard in opponent.graveyard


def test_chatterfang_adds_matching_squirrels_and_doublers_apply_once_to_the_batch():
    from mtg_analyzer.models.cards.card import Card
    engine, player, chatter = game('Chatterfang, Squirrel General')
    token = Card(id='bear', name='Bear', type_line='Token Creature — Bear', is_creature=True, power=2, toughness=2)
    engine.rules.create_token('p1', token, 2)
    assert len([o for o in engine.state.battlefield if o.is_token and o.name == 'Squirrel']) == 2
    season = GameObject(CardDatabase(DB_PATH).get_card('Doubling Season'), owner_id='p1', zone=Zone.BATTLEFIELD)
    season.controller_id = 'p1'
    bind_from_catalogue(season)
    engine.state.add_to_battlefield(season)
    before = len([o for o in engine.state.battlefield if o.is_token])
    engine.rules.create_token('p1', token, 1)
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        engine.resolve_pending_choice(engine.state.pending_choice['options'][0]['id'])
        engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.is_token]) == before + 4


def test_maskwood_nexus_grants_every_type_in_hand_and_on_board_and_stops_on_leave():
    from mtg_analyzer.game.continuous import has_subtype
    engine, player, nexus = game('Maskwood Nexus')
    bear = battlefield_object(engine, 'p1', 'Bear', 'Creature — Bear', is_creature=True, power=2, toughness=2)
    elf = GameObject(CardDatabase(DB_PATH).get_card('Llanowar Elves'), owner_id='p1', zone=Zone.HAND)
    player.hand.append(elf)
    engine.recompute_continuous_effects()
    assert has_subtype(bear, 'Squirrel') and has_subtype(elf, 'Squirrel')
    engine.rules.destroy(nexus)
    engine.recompute_continuous_effects()
    assert not has_subtype(bear, 'Squirrel') and not has_subtype(elf, 'Squirrel')


def test_swarmyard_massacre_counts_new_squirrels_and_spares_the_named_types():
    engine, player, _ = game('Chitterspitter')
    rat = battlefield_object(engine, 'p1', 'Rat', 'Creature — Rat', is_creature=True, power=2, toughness=2)
    bear = battlefield_object(engine, 'p2', 'Bear', 'Creature — Bear', is_creature=True, power=4, toughness=4)
    cast(engine, player, 'Swarmyard Massacre')
    engine.recompute_continuous_effects()
    assert rat.power == 2 and bear.power == 1
    assert len([o for o in engine.state.battlefield if o.is_token]) == 2


def test_sword_of_the_squeak_counts_base_power_or_toughness_once_per_creature():
    engine, player, sword = game('Sword of the Squeak')
    host = battlefield_object(engine, 'p1', 'Host', 'Creature — Bear', is_creature=True, power=1, toughness=1)
    host.counters['+1/+1'] = 3
    small = battlefield_object(engine, 'p1', 'Small', 'Creature — Rat', is_creature=True, power=3, toughness=1)
    sword.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    assert (host.power, host.toughness) == (6, 6)
    assert small.power == 3


def test_cache_grab_recovers_only_a_milled_permanent_and_rewards_a_returned_squirrel():
    engine, player, _ = game('Chitterspitter')
    cards = [CardDatabase(DB_PATH).get_card(n) for n in ['Nested Shambler', 'Forest', 'Swarmyard', 'Chatterfang, Squirrel General']]
    player.library[:] = [GameObject(c, owner_id='p1', zone=Zone.LIBRARY) for c in cards]
    squirrel = player.library[-1]
    cast(engine, player, 'Cache Grab')
    assert engine.state.pending_choice
    engine.resolve_pending_choice(str(squirrel.instance_id))
    engine.resolve_until_stable()
    assert squirrel in player.hand and len(player.graveyard) == 4  # three milled cards + the spell
    assert len([o for o in engine.state.battlefield if o.name == 'Food']) == 1


def test_cache_grab_declining_without_a_squirrel_creates_no_food():
    engine, player, _ = game('Chitterspitter')
    player.library[:] = [GameObject(CardDatabase(DB_PATH).get_card('Forest'), owner_id='p1', zone=Zone.LIBRARY)]
    cast(engine, player, 'Cache Grab')
    engine.resolve_pending_choice('decline')
    engine.resolve_until_stable()
    assert not any(o.is_token for o in engine.state.battlefield)


def test_frugivore_repeats_food_creation_only_when_three_graveyard_cards_are_exiled():
    engine, player, frugivore = game('Insatiable Frugivore')
    player.graveyard[:] = [GameObject(CardDatabase(DB_PATH).get_card('Forest'), owner_id='p1', zone=Zone.GRAVEYARD) for _ in range(3)]
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=frugivore.instance_id, controller_id='p1'))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.name == 'Food']) == 1
    while engine.state.pending_choice:
        options = engine.state.pending_choice['options']
        selected = next((o for o in options if o['id'] == 'pay'), next(o for o in options if o['id'] != 'decline'))
        engine.resolve_pending_choice(selected['id'])
        engine.resolve_until_stable()
    assert len([o for o in engine.state.battlefield if o.name == 'Food']) == 2
    assert not player.graveyard and len(player.exile) == 3


def test_brewmaster_food_borrows_mana_abilities_as_well_as_stack_abilities():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for
    engine, player, brew = game("Hazel's Brewmaster")
    elf = GameObject(CardDatabase(DB_PATH).get_card('Llanowar Elves'), owner_id='p1', zone=Zone.EXILE)
    bind_from_catalogue(elf)
    player.exile.append(elf)
    brew.exiled_with_ids.append(elf.instance_id)
    from mtg_analyzer.services.token_database import default_token_database
    food = engine.rules.create_token('p1', default_token_database().get_token('Food'))[0]
    engine.recompute_continuous_effects()
    assert mana_abilities_for(food, engine.state)
    engine.tap_for_mana(player, food)
    assert food.tapped and player.mana_pool.pool['G'] == 1
    engine.rules.return_to_hand(elf)
    engine.recompute_continuous_effects()
    assert not mana_abilities_for(food, engine.state)


def test_chatterfang_sacrifices_paid_x_squirrels_and_pumps_the_target_by_x_minus_x():
    from mtg_analyzer.models.cards.card import Card
    engine, player, chatter = game('Chatterfang, Squirrel General')
    squirrels = engine.rules.create_token('p1', Card(id='sq', name='Squirrel', type_line='Token Creature — Squirrel', is_creature=True, power=1, toughness=1))
    # Replacement adds a second Squirrel.
    target = battlefield_object(engine, 'p2', 'Victim', 'Creature — Bear', is_creature=True, power=3, toughness=5)
    player.mana_pool.add_many({'B': 1})
    fodder = [o.instance_id for o in engine.state.battlefield if o.is_token]
    engine.activate_ability(player, chatter, 0, targets=[target], x=2, tap_choices=fodder)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert (target.power, target.toughness) == (5, 3)
    assert not any(o.is_token for o in engine.state.battlefield)


def test_frugivore_paid_foods_pump_all_own_creatures_and_grant_menace():
    from mtg_analyzer.services.token_database import default_token_database
    engine, player, frugivore = game('Insatiable Frugivore')
    food = engine.rules.create_token('p1', default_token_database().get_token('Food'), 2)
    player.mana_pool.add_many({'B': 1, 'C': 3})
    engine.activate_ability(player, frugivore, 0, x=2, tap_choices=[o.instance_id for o in food])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert frugivore.power == frugivore.card.power + 2 and 'menace' in frugivore.granted_keywords
    assert not any(o.name == 'Food' for o in engine.state.battlefield)


def test_hazels_mana_ability_taps_chosen_tokens_pays_life_and_resolves_without_stack():
    from mtg_analyzer.services.token_database import default_token_database
    engine, player, hazel = game('Hazel of the Rootbloom')
    foods = engine.rules.create_token('p1', default_token_database().get_token('Food'), 2)
    engine.tap_for_mana(player, hazel, x=2, tap_choices=[o.instance_id for o in foods], color_split={'B': 1, 'G': 1})
    assert player.life == 18 and hazel.tapped and all(o.tapped for o in foods)
    assert player.mana_pool.pool['B'] == 1 and player.mana_pool.pool['G'] == 1
    assert not engine.state.stack


def test_skyfisher_spider_death_gain_counts_itself_then_exiles_it():
    engine, player, spider = game('Skyfisher Spider')
    player.graveyard.append(GameObject(CardDatabase(DB_PATH).get_card('Nested Shambler'), owner_id='p1', zone=Zone.GRAVEYARD))
    engine.rules.destroy(spider)
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice
    engine.resolve_pending_choice(engine.state.pending_choice['options'][0]['id'])
    engine.resolve_until_stable()
    assert player.life == 22 and spider in player.exile and spider not in player.graveyard


def test_sword_may_attach_to_the_rat_that_entered_without_targeting_it():
    from mtg_analyzer.models.cards.card import Card
    engine, player, sword = game('Sword of the Squeak')
    rat = engine.rules.create_token('p1', Card(id='rat', name='Rat', type_line='Token Creature — Rat', is_creature=True, power=1, toughness=1))[0]
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice
    engine.resolve_pending_choice(engine.state.pending_choice['options'][0]['id'])
    engine.resolve_until_stable()
    assert sword.attached_to == rat.instance_id


def test_maskwood_nexus_makes_a_bear_trigger_sword_but_not_become_food_or_forest():
    from mtg_analyzer.game.continuous import has_subtype
    from mtg_analyzer.models.cards.card import Card
    engine, player, sword = game('Sword of the Squeak')
    nexus = GameObject(CardDatabase(DB_PATH).get_card('Maskwood Nexus'), owner_id='p1', zone=Zone.BATTLEFIELD)
    bind_from_catalogue(nexus)
    engine.state.add_to_battlefield(nexus)
    bear = engine.rules.create_token('p1', Card(id='bear', name='Bear', type_line='Token Creature — Bear', is_creature=True, power=2, toughness=2))[0]
    assert has_subtype(bear, 'Squirrel') and has_subtype(bear, 'Time Lord')
    assert not has_subtype(bear, 'Food') and not has_subtype(bear, 'Forest')
    engine.rules.put_triggers_on_stack()
    assert engine.state.pending_choice
    engine.resolve_pending_choice(engine.state.pending_choice['options'][0]['id'])
    engine.resolve_until_stable()
    assert sword.attached_to == bear.instance_id


def test_token_hazel_cannot_pay_her_own_tap_symbol_and_token_tap_with_one_object():
    import pytest
    engine, player, hazel = game('Hazel of the Rootbloom')
    hazel.is_token = True
    with pytest.raises(ValueError):
        engine.tap_for_mana(player, hazel, x=1, tap_choices=[hazel.instance_id], color_split={'G': 1})
    assert not hazel.tapped and player.life == 20
