"""Gameplay regressions for the saved-deck modeling queue."""
from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.card_cache import get_cached_card
from tests.support.catalogue import battlefield_object, two_player_game


def board(engine, name):
    card = get_cached_card(name)
    assert card is not None
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    engine.recompute_continuous_effects()
    return obj


def test_last_ride_tracks_life_and_draw_payment():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    player.life = 9
    ride = board(engine, "The Last Ride")
    crew = battlefield_object(engine, "p1", "Crew", "Creature", is_creature=True, power=2, toughness=2)
    crew.summoning_sick = False
    crew_index = next(i for i, a in enumerate(ride.activated_abilities) if a.cost.crew_power)
    draw_index = next(i for i, a in enumerate(ride.activated_abilities) if not a.cost.crew_power)
    engine.activate_ability(player, ride, ability_index=crew_index, tap_choices=[crew.instance_id])
    engine.resolve_until_stable()
    assert ride.power == ride.card.vehicle_power - player.life
    player.life = 7
    engine.recompute_continuous_effects()
    assert ride.power == ride.card.vehicle_power - 7
    card = GameObject(Card(id="draw", name="Draw", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY)
    player.library.append(card)
    player.mana_pool.add_many({"B": 1, "C": 2})
    engine.activate_ability(player, ride, ability_index=draw_index)
    engine.resolve_until_stable()
    assert player.life == 5 and card in player.hand
    assert ride.power == ride.card.vehicle_power - 5
    assert len(ride.activated_abilities) == 2


def test_soulcleaver_counts_artifacts_and_creatures_once_each():
    engine, player = two_player_game()
    equipment = board(engine, "Tarrian's Soulcleaver")
    host = battlefield_object(engine, "p1", "Host", "Creature", is_creature=True, power=2, toughness=2)
    equipment.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    assert combat.has(host, "vigilance")
    for name, type_line in [("Rock", "Artifact"), ("Golem", "Artifact Creature"), ("Bear", "Creature")]:
        victim = battlefield_object(engine, "p2", name, type_line,
                                    is_creature="Creature" in type_line, power=2 if "Creature" in type_line else None,
                                    toughness=2 if "Creature" in type_line else None)
        engine.rules.destroy(victim)
        engine.resolve_until_stable()
    assert host.counters.get("+1/+1") == 3
    land = battlefield_object(engine, "p2", "Land", "Land", is_land=True)
    engine.rules.destroy(land)
    engine.resolve_until_stable()
    assert host.counters.get("+1/+1") == 3
    engine.rules.destroy(equipment)
    engine.resolve_until_stable()
    assert host.counters.get("+1/+1") == 3


def test_evolved_sleeper_requires_each_form_and_keeps_its_counters():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    sleeper = board(engine, "Evolved Sleeper")
    player.mana_pool.add_many({"B": 8, "C": 8})
    engine.activate_ability(player, sleeper, ability_index=1)
    engine.resolve_until_stable()
    assert sleeper.power == 1 and not sleeper.counters
    engine.activate_ability(player, sleeper, ability_index=0)
    engine.resolve_until_stable()
    assert sleeper.power == 2
    engine.activate_ability(player, sleeper, ability_index=1)
    engine.resolve_until_stable()
    assert sleeper.power == 3 and combat.has(sleeper, "deathtouch")
    card = GameObject(Card(id="draw", name="Draw", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY)
    player.library.append(card)
    engine.activate_ability(player, sleeper, ability_index=2)
    engine.resolve_until_stable()
    assert sleeper.power == 4 and card in player.hand and player.life == 19
    engine.activate_ability(player, sleeper, ability_index=0)
    engine.resolve_until_stable()
    assert sleeper.power == 3 and combat.has(sleeper, "deathtouch")
    engine.activate_ability(player, sleeper, ability_index=2)
    engine.resolve_until_stable()
    assert sleeper.power == 3 and player.life == 19


def test_cultist_grants_owned_commander_stats_ward_and_upkeep():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    commander = battlefield_object(engine, "p1", "Commander", "Creature", is_creature=True, power=2, toughness=2)
    commander.is_commander = True
    fodder = battlefield_object(engine, "p1", "Fodder", "Creature", is_creature=True, power=1, toughness=1)
    board(engine, "Cultist of the Absolute")
    assert commander.power == 5 and combat.has(commander, "deathtouch") and combat.has(commander, "flying")
    assert commander.granted_ward_cost == "Pay 3 life"
    assert fodder.power == 1 and not combat.has(fodder, "flying")
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, player_id="p1", step="upkeep"))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None
    engine.resolve_pending_choice(str(fodder.instance_id))
    engine.resolve_until_stable()
    assert fodder.zone == Zone.GRAVEYARD


def test_noise_marine_etb_counts_only_its_controllers_spells():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    marine = board(engine, "Noise Marine")
    for pid, count in [("p1", 3), ("p2", 8)]:
        for _ in range(count):
            engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=pid))
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=marine.instance_id,
                                         controller_id="p1"))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if "p2" in str(o)))
    engine.resolve_until_stable()
    assert engine.state.player_by_id("p2").life == 17


import pytest


@pytest.mark.parametrize("name,subtype", [("Circuitous Route", "Gate"), ("Map the Frontier", "Desert"),
                                         ("Reach the Horizon", "Town")])
def test_land_search_allows_basic_or_subtype_and_enforces_distinct_names(name, subtype):
    from mtg_analyzer.parser.oracle import parse_oracle
    engine, player = two_player_game()
    real = get_cached_card(name)
    assert parse_oracle(real).modeled
    spell = GameObject(real, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    engine.begin_turn()
    engine.state.current_step = "main1"
    candidates = []
    for i, (card_name, type_line) in enumerate([
        ("Forest", "Basic Land — Forest"), ("Forest", "Basic Land — Forest"),
        ("Special", f"Land — {subtype}"), ("Bad", "Land"),
    ]):
        obj = GameObject(Card(id=str(i), name=card_name, type_line=type_line, is_land=True),
                         owner_id="p1", zone=Zone.LIBRARY)
        player.library.append(obj)
        candidates.append(obj)
    player.mana_pool.add_many({"G": 2, "C": 6})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()
    choices = engine.state.pending_choice["options"]
    assert not any(o.get("instance_id") == candidates[3].instance_id for o in choices)
    engine.resolve_pending_choice(str(candidates[0].instance_id))
    choices = engine.state.pending_choice["options"]
    assert any(o.get("instance_id") == candidates[1].instance_id for o in choices) == (subtype != "Town")
    engine.resolve_pending_choice(str(candidates[2].instance_id))
    engine.resolve_until_stable()
    assert all(o.zone == Zone.BATTLEFIELD and o.tapped for o in (candidates[0], candidates[2]))


def test_woodwurm_measures_power_for_both_look_and_mana_value():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    wurm = board(engine, "Emergent Woodwurm")
    cards = []
    for i, mv in enumerate([1, 9, 2]):
        obj = GameObject(Card(id=str(i), name=f"Creature {mv}", type_line="Creature", is_creature=True,
                              power=1, toughness=1, converted_mana_cost=mv), owner_id="p1", zone=Zone.LIBRARY)
        player.library.append(obj)
        cards.append(obj)
    wurm.temp_power = -2
    engine.recompute_continuous_effects()
    assert wurm.power == 2
    engine.state.fire_event(GameEvent(EventType.ATTACKS, instance_id=wurm.instance_id, controller_id="p1"))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None
    assert any(o.get("instance_id") == cards[2].instance_id for o in choice["options"])
    assert not any(o.get("instance_id") in [cards[0].instance_id, cards[1].instance_id] for o in choice["options"])
    engine.resolve_pending_choice(str(cards[2].instance_id))
    engine.resolve_until_stable()
    assert cards[2].zone == Zone.BATTLEFIELD
    assert cards[1] == player.library[0]


def stock(player, count):
    for i in range(count):
        player.library.append(GameObject(Card(id=f"lib{i}", name=f"Library {i}", type_line="Land", is_land=True),
                                         owner_id=player.id, zone=Zone.LIBRARY))


@pytest.mark.parametrize("helpers", [0, 2, 4])
def test_heirloom_epic_substitutes_creature_taps_for_mana(helpers):
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    epic = board(engine, "Heirloom Epic")
    creatures = [battlefield_object(engine, "p1", f"Helper {i}", "Creature", is_creature=True, power=1, toughness=1)
                 for i in range(helpers)]
    stock(player, 2)
    player.mana_pool.add_many({"C": 4 - helpers})
    engine.activate_ability(player, epic, x=helpers, tap_choices=[c.instance_id for c in creatures])
    engine.resolve_until_stable()
    assert len(player.hand) == 1 and epic.tapped and all(c.tapped for c in creatures)


def test_spry_and_mighty_uses_untargeted_exactly_two_and_freezes_difference():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    small = battlefield_object(engine, "p1", "Small", "Creature", is_creature=True, power=1, toughness=2)
    big = battlefield_object(engine, "p1", "Big", "Creature", is_creature=True, power=4, toughness=4)
    battlefield_object(engine, "p1", "Other", "Creature", is_creature=True, power=2, toughness=2)
    spell = GameObject(get_cached_card("Spry and Mighty"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    stock(player, 8)
    player.mana_pool.add_many({"G": 2, "C": 6})
    engine.cast_spell(player, spell)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(small.instance_id))
    engine.resolve_pending_choice(str(big.instance_id))
    engine.resolve_until_stable()
    assert len(player.hand) == 3
    assert (small.power, big.power) == (4, 7)
    assert combat.has(small, "trample") and combat.has(big, "trample")


def test_sweet_gum_recluse_only_offers_creatures_entered_this_turn():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    old = battlefield_object(engine, "p1", "Old", "Creature", is_creature=True, power=1, toughness=1)
    old.turn_entered = engine.state.internal_turn.number - 1
    fresh = battlefield_object(engine, "p2", "Fresh", "Creature", is_creature=True, power=1, toughness=1)
    recluse = board(engine, "Sweet-Gum Recluse")
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=recluse.instance_id, controller_id="p1"))
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert choice is not None
    assert not any(o.get("instance_id") == old.instance_id for o in choice["options"])
    engine.resolve_pending_choice(str(fresh.instance_id))
    if engine.state.pending_choice:
        engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    assert fresh.counters.get("+1/+1") == 3


@pytest.mark.parametrize("kicked", [False, True])
def test_hunting_wilds_animates_only_the_found_forests_when_kicked(kicked):
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    old = battlefield_object(engine, "p1", "Old Forest", "Basic Land — Forest", is_land=True)
    forests = []
    for i in range(2):
        obj = GameObject(get_cached_card("Forest"), owner_id="p1", zone=Zone.LIBRARY)
        player.library.append(obj)
        forests.append(obj)
    spell = GameObject(get_cached_card("Hunting Wilds"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.hand.append(spell)
    player.mana_pool.add_many({"G": 2, "C": 8})
    engine.cast_spell(player, spell, kicked=1 if kicked else 0)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(forests[0].instance_id))
    # Fail to find the second Forest: the first find must still receive the rider.
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert forests[0].zone == Zone.BATTLEFIELD
    assert forests[0].tapped is not kicked
    assert forests[0].is_creature is kicked
    if kicked:
        assert forests[0].power == 3 and forests[0].toughness == 3 and combat.has(forests[0], "haste")
    assert not old.is_creature


def test_tannuk_grants_warp_and_removes_the_grant_on_departure():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    tannuk = board(engine, "Tannuk, Steadfast Second")
    artifact = GameObject(get_cached_card("Sol Ring"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(artifact)
    player.hand.append(artifact)
    assert engine._warp_cost(artifact).raw == "{2}{R}"
    player.mana_pool.add_many({"R": 1, "C": 2})
    engine.cast_spell(player, artifact, warp=True)
    engine.resolve_until_stable()
    assert artifact.zone == Zone.BATTLEFIELD and artifact.cast_via_warp
    other = GameObject(get_cached_card("Sol Ring"), owner_id="p1", zone=Zone.HAND)
    player.hand.append(other)
    engine.rules.destroy(tannuk)
    engine.resolve_until_stable()
    assert engine._warp_cost(other) is None


def test_tinybones_legendary_entry_mills_and_drains_each_chosen_player():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    board(engine, "Tinybones Joins Up")
    stock(player, 2)
    opponent = engine.state.player_by_id("p2")
    stock(opponent, 2)
    creature = battlefield_object(engine, "p1", "Legend", "Legendary Creature", is_creature=True,
                                  is_legendary=True, power=2, toughness=2)
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=creature.instance_id,
                                     controller_id="p1"))
    engine.resolve_until_stable()
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice("p1")
    engine.resolve_pending_choice("p2")
    if engine.state.pending_choice:
        engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    assert len(player.graveyard) == 1 and len(opponent.graveyard) == 1
    assert player.life == opponent.life == 19


def test_bigger_on_the_inside_gives_target_mana_and_next_spell_cascade():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    host = battlefield_object(engine, "p1", "Rock", "Artifact")
    aura = board(engine, "Bigger on the Inside")
    aura.attached_to = host.instance_id
    engine.recompute_continuous_effects()
    opponent = engine.state.player_by_id("p2")
    engine.activate_ability(player, host, ability_index=0, targets=[opponent])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is not None
    engine.resolve_pending_choice("G")
    engine.resolve_until_stable()
    assert opponent.mana_pool.pool.get("G", 0) == 2
    assert engine.state.next_spell_cascade_grants == [{"player_id": "p2", "turn": engine.state.internal_turn.number}]

    clone = engine.state.clone()
    assert clone.next_spell_cascade_grants == engine.state.next_spell_cascade_grants
    own_spell = GameObject(get_cached_card("Sol Ring"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(own_spell)
    player.hand.append(own_spell)
    player.mana_pool.add_many({"C": 1})
    engine.cast_spell(player, own_spell)
    assert len(engine.state.next_spell_cascade_grants) == 1
    enemy_spell = GameObject(get_cached_card("Opt"), owner_id="p2", zone=Zone.HAND)
    bind_from_catalogue(enemy_spell)
    opponent.hand.append(enemy_spell)
    opponent.mana_pool.add_many({"U": 1})
    engine.cast_spell(opponent, enemy_spell)
    assert engine.state.next_spell_cascade_grants == []
    assert any("Cascade" in ability.description for ability, event in engine.rules.pending_triggers)


def test_tinybones_entry_discard_can_choose_both_players():
    from mtg_analyzer.models.game.events import EventType, GameEvent
    engine, player = two_player_game()
    engine.begin_turn()
    tinybones = board(engine, "Tinybones Joins Up")
    for p in engine.state.players:
        p.hand.append(GameObject(Card(id=p.id, name="Discard", type_line="Land", is_land=True),
                                 owner_id=p.id, zone=Zone.HAND))
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=tinybones.instance_id,
                                     controller_id="p1"))
    engine.resolve_until_stable()
    engine.resolve_pending_choice("p1")
    engine.resolve_pending_choice("p2")
    if engine.state.pending_choice:
        engine.resolve_pending_choice("stop")
    engine.resolve_until_stable()
    assert all(not p.hand and len(p.graveyard) == 1 for p in engine.state.players)


def test_heirloom_rejects_duplicate_helpers_and_instant_speed():
    engine, player = two_player_game()
    engine.begin_turn()
    engine.state.current_step = "main1"
    epic = board(engine, "Heirloom Epic")
    helper = battlefield_object(engine, "p1", "Helper", "Creature", is_creature=True, power=1, toughness=1)
    player.mana_pool.add_many({"C": 4})
    with pytest.raises(ValueError):
        engine.activate_ability(player, epic, x=2, tap_choices=[helper.instance_id, helper.instance_id])
    assert not epic.tapped and not helper.tapped
    engine.state.current_step = "upkeep"
    assert not engine.can_activate(player, epic, epic.activated_abilities[0])


def test_shared_search_and_attached_counter_grammar_fail_closed():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    assert match_clause("search your library for up to 2 basic land cards and/or imaginary cards, put them onto the battlefield tapped, then shuffle.") is None
    assert match_clause("search your library for up to 2 basic land cards and/or gate cards with the same name, put them onto the battlefield tapped, then shuffle.") is None
    assert match_clause("put a +1/+1 counter on that creature.") is None
