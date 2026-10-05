"""Hand-authored cards of the saved "Oops! All Night's Whispers" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

import pytest
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat
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
    for i in range(4):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    return engine, p1, engine.state.player_by_id("p2")


def _cast_wisps(name, color, keyword):
    engine, p1, p2 = _game(name)
    bear = battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"G"})
    p1.mana_pool.add_many({"B": 1, "R": 1, "U": 1})
    hand_before = len(p1.hand)
    engine.cast_spell(p1, p1.hand[0], targets=[bear])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert len(p1.hand) == hand_before - 1 + 1  # the spell left the hand, "draw a card" refilled it
    assert bear.colors == {color} and combat.has(bear, keyword)  # "becomes <colour>" replaces green

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert bear.colors == {"G"} and not combat.has(bear, keyword)  # until end of turn


def test_aphotic_wisps_makes_the_creature_black_with_fear_and_draws():
    _cast_wisps("Aphotic Wisps", "B", "fear")


def test_crimson_wisps_makes_the_creature_red_with_haste_and_draws():
    _cast_wisps("Crimson Wisps", "R", "haste")


def _creature_card(name, owner):
    return GameObject(
        Card(id=name, name=name, type_line="Creature — Beast", is_creature=True, power=2, toughness=2),
        owner_id=owner, zone=Zone.GRAVEYARD,
    )


def test_exhume_lets_each_player_choose_a_creature_from_their_own_graveyard():
    engine, p1, p2 = _game("Exhume")
    mine = [_creature_card("My Beast", "p1"), _creature_card("My Other Beast", "p1")]
    theirs = [_creature_card("Their Beast", "p2"), _creature_card("Their Other Beast", "p2")]
    p1.graveyard.extend(mine)
    p2.graveyard.extend(theirs)
    p1.mana_pool.add_many({"B": 1, "C": 1})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()

    first = engine.state.pending_choice
    assert first["player_id"] == "p1" and {o["label"] for o in first["options"] if "instance_id" in o} == {"My Beast", "My Other Beast"}
    engine.resolve_pending_choice(next(o["id"] for o in first["options"] if o.get("label") == "My Other Beast"))
    engine.resolve_until_stable()
    second = engine.state.pending_choice
    assert second["player_id"] == "p2" and {o["label"] for o in second["options"] if "instance_id" in o} == {"Their Beast", "Their Other Beast"}
    engine.resolve_pending_choice(next(o["id"] for o in second["options"] if o.get("label") == "Their Beast"))
    engine.resolve_until_stable()

    assert mine[1].zone == Zone.BATTLEFIELD and mine[1].controller_id == "p1" and mine[0].zone == Zone.GRAVEYARD
    assert theirs[0].zone == Zone.BATTLEFIELD and theirs[0].controller_id == "p2" and theirs[1].zone == Zone.GRAVEYARD


def _fill_graveyard(player, n):
    for i in range(n):
        player.graveyard.append(GameObject(Card(id=f"F{i}", name=f"Filler {i}", type_line="Sorcery", is_sorcery=True), owner_id=player.id, zone=Zone.GRAVEYARD))


def test_living_death_returns_old_graveyards_and_leaves_sacrificed_creatures_dead():
    engine, p1, p2 = _game("Living Death")
    old = [_creature_card("Old A", "p1"), _creature_card("Old B", "p2")]
    p1.graveyard.append(old[0])
    p2.graveyard.append(old[1])
    live = [battlefield_object(engine, pid, f"Live {pid}", "Creature — Beast",
                              is_creature=True, power=3, toughness=3)
            for pid in ("p1", "p2")]
    live[0].intrinsic_keywords.add("indestructible")
    live[1].controller_id = "p1"  # stolen creature still returns to its owner's graveyard
    p1.mana_pool.add_many({"B": 2, "C": 3})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    assert all(obj.zone == Zone.BATTLEFIELD for obj in old)
    assert [obj.controller_id for obj in old] == ["p1", "p2"]
    assert all(obj.zone == Zone.GRAVEYARD for obj in live)
    assert live[1] in p2.graveyard


def test_victimize_keeps_targets_across_the_sacrifice_choice_and_returns_them_tapped():
    engine, p1, p2 = _game("Victimize")
    old = [_creature_card("Old A", "p1"), _creature_card("Old B", "p1")]
    p1.graveyard.extend(old)
    live = [battlefield_object(engine, "p1", f"Live {i}", "Creature — Beast",
                              is_creature=True, power=3, toughness=3) for i in range(2)]
    p1.mana_pool.add_many({"B": 1, "C": 2})
    engine.cast_spell(p1, p1.hand[0], targets=old)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"]
                                       if o.get("instance_id") == live[1].instance_id))
    engine.resolve_until_stable()
    assert live[1].zone == Zone.GRAVEYARD and live[0].zone == Zone.BATTLEFIELD
    assert all(obj.zone == Zone.BATTLEFIELD and obj.tapped for obj in old)


def test_victimize_does_not_return_anything_without_a_sacrificable_creature():
    engine, p1, p2 = _game("Victimize")
    old = [_creature_card("Old A", "p1"), _creature_card("Old B", "p1")]
    p1.graveyard.extend(old)
    p1.mana_pool.add_many({"B": 1, "C": 2})
    engine.cast_spell(p1, p1.hand[0], targets=old)
    engine.resolve_until_stable()
    assert all(obj.zone == Zone.GRAVEYARD for obj in old)


def test_sewer_nemesis_chooses_self_before_entry_and_mills_only_the_chosen_caster():
    engine, p1, p2 = _game("Sewer Nemesis")
    _fill_graveyard(p1, 3)
    nemesis = p1.hand[0]
    p1.mana_pool.add_many({"B": 1, "C": 3})
    engine.cast_spell(p1, nemesis)
    engine.resolve_until_stable()
    assert nemesis.zone != Zone.BATTLEFIELD
    assert {o["id"] for o in engine.state.pending_choice["options"]} == {"p1", "p2"}
    engine.resolve_pending_choice("p1")
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert nemesis.zone == Zone.BATTLEFIELD and nemesis.power == nemesis.toughness == 3
    p1.mana_pool.add_many({"C": 1})
    rock = GameObject(Card(id="rock", name="Rock", type_line="Artifact", mana_cost_string="{1}"),
                      owner_id="p1", zone=Zone.HAND)
    p1.hand.append(rock)
    before = len(p1.library)
    engine.cast_spell(p1, rock)
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert len(p1.library) == before - 1 and nemesis.power == 4


@pytest.mark.parametrize("gift,legendary,copies", [(False, False, 0), (True, False, 1), (True, True, 0)])
def test_coiling_rebirth_copies_only_a_nonlegendary_return_with_a_promised_gift(gift, legendary, copies):
    engine, p1, p2 = _game("Coiling Rebirth")
    creature = GameObject(Card(id="fallen", name="Fallen", type_line="Legendary Creature" if legendary else "Creature",
                               is_creature=True, is_legendary=legendary, power=4, toughness=5),
                          owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(creature)
    p2.library.append(GameObject(Card(id="gift", name="Gift", type_line="Land"), owner_id="p2", zone=Zone.LIBRARY))
    p1.mana_pool.add_many({"B": 2, "C": 3})
    engine.cast_spell(p1, p1.hand[0], targets=[creature], gift_opponent_id="p2" if gift else None)
    engine.resolve_until_stable()
    assert creature.zone == Zone.BATTLEFIELD
    tokens = [o for o in engine.state.battlefield if o.is_token and o.name == "Fallen"]
    assert len(tokens) == copies
    assert all((o.power, o.toughness) == (1, 1) for o in tokens)
    assert len(p2.hand) == int(gift)


def test_fable_chapters_make_an_attacking_treasure_goblin_loot_and_transform():
    engine, p1, p2 = _game("Fable of the Mirror-Breaker")
    saga = p1.hand[0]
    p1.mana_pool.add_many({"R": 1, "C": 2})
    engine.cast_spell(p1, saga)
    engine.resolve_until_stable()
    goblin = next(o for o in engine.state.battlefield if o.is_token)
    assert (goblin.power, goblin.toughness) == (2, 2)
    goblin.summoning_sick = False
    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(p1, [goblin])
    engine.resolve_until_stable()
    assert sum(o.name == "Treasure" for o in engine.state.battlefield) == 1

    p1.hand.extend([GameObject(Card(id=f"h{i}", name=f"Hand {i}", type_line="Land"),
                              owner_id="p1", zone=Zone.HAND) for i in range(3)])
    engine.rules.advance_sagas(p1)
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if "instance_id" in o))
    engine.resolve_until_stable()
    engine.resolve_pending_choice("decline")
    engine.resolve_until_stable()
    assert len(p1.hand) == 3  # one discarded, exactly one drawn

    engine.rules.advance_sagas(p1)
    engine.resolve_until_stable()
    assert saga.zone == Zone.BATTLEFIELD and saga.transformed
    assert saga.name == "Reflection of Kiki-Jiki" and saga.activated_abilities
    saga.summoning_sick = False
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 1})
    engine.activate_ability(p1, saga, 0, targets=[goblin])
    engine.resolve_until_stable()
    assert sum(o.name == goblin.name for o in engine.state.battlefield) == 2


def test_breach_mills_every_player_and_returns_their_chosen_cards_under_my_control():
    engine, p1, p2 = _game("Breach the Multiverse")
    mine = [_creature_card("Mine A", "p1"), _creature_card("Mine B", "p1")]
    theirs = [_creature_card("Theirs A", "p2"), _creature_card("Theirs B", "p2")]
    p1.graveyard.extend(mine)
    p2.graveyard.extend(theirs)
    p1.mana_pool.add_many({"B": 2, "C": 5})
    engine.cast_spell(p1, p1.hand[0])
    engine.resolve_until_stable()
    for chosen in [mine[1], theirs[0]]:
        choice = engine.state.pending_choice
        engine.resolve_pending_choice(next(o["id"] for o in choice["options"]
                                           if o.get("instance_id") == chosen.instance_id))
        engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not p1.library and not p2.library
    assert all(o.zone == Zone.BATTLEFIELD and o.controller_id == "p1" for o in [mine[1], theirs[0]])
    from mtg_analyzer.game.continuous import has_subtype
    assert all(has_subtype(o, "Phyrexian") for o in [mine[1], theirs[0]])
    assert mine[0].zone == theirs[1].zone == Zone.GRAVEYARD
    later = battlefield_object(engine, "p1", "Later", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()
    assert not has_subtype(later, "Phyrexian")


@pytest.mark.parametrize("pay", [True, False])
def test_ripples_payment_recovers_only_one_of_this_mill_batch(pay):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    ripples = GameObject(CardDatabase(DB_PATH).get_card("Ripples of Undeath"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(ripples)
    engine.state.add_to_battlefield(ripples)
    old = _creature_card("Old", "p1")
    p1.graveyard.append(old)
    milled = list(p1.library[-3:])
    p1.mana_pool.add_many({"C": 1})
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main1", player_id="p1"))
    engine.resolve_until_stable()
    assert all(o.zone == Zone.GRAVEYARD for o in milled)
    engine.resolve_pending_choice("pay" if pay else "decline")
    engine.resolve_until_stable()
    if pay:
        choice = engine.state.pending_choice
        assert {o["instance_id"] for o in choice["options"] if "instance_id" in o} == {o.instance_id for o in milled}
        engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("instance_id") == milled[0].instance_id))
        engine.resolve_until_stable()
        assert milled[0].zone == Zone.HAND
    assert p1.life == (17 if pay else 20) and old.zone == Zone.GRAVEYARD


@pytest.mark.parametrize("draw", [True, False])
def test_palantir_targets_the_opponent_who_decides_between_a_draw_and_mill_life_loss(draw):
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    palantir = GameObject(CardDatabase(DB_PATH).get_card("Palantír of Orthanc"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(palantir)
    engine.state.add_to_battlefield(palantir)
    p1.library[-1] = GameObject(Card(id="costly", name="Costly", type_line="Sorcery", is_sorcery=True,
                                    converted_mana_cost=5), owner_id="p1", zone=Zone.LIBRARY)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1"))
    engine.rules.put_triggers_on_stack()
    choice = engine.state.pending_choice
    engine.resolve_pending_choice("p2")
    engine.resolve_until_stable()
    while engine.state.pending_choice and engine.state.pending_choice["kind"] == "scry":
        engine.resolve_pending_choice("decline")
        engine.resolve_until_stable()
    assert palantir.counters["influence"] == 1
    assert engine.state.pending_choice["player_id"] == "p2"
    engine.resolve_pending_choice("pay" if draw else "decline")
    engine.resolve_until_stable()
    assert len(p1.hand) == int(draw)
    assert p2.life == (20 if draw else 15)


def test_prismari_grants_storm_to_the_spell_and_captures_cast_count_before_responses():
    engine, p1, p2 = _game()
    prismari = GameObject(CardDatabase(DB_PATH).get_card("Prismari, the Inspiration"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(prismari)
    engine.state.add_to_battlefield(prismari)

    def spell(name, text, type_line="Sorcery", **flags):
        obj = GameObject(Card(id=name, name=name, type_line=type_line, oracle_text=text, **flags), owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.hand.append(obj)
        return obj

    rock = spell("Rock", "", "Artifact")
    engine.cast_spell(p1, rock)
    engine.resolve_until_stable()
    spell_obj = spell("Study", "Draw a card.", is_sorcery=True)
    engine.cast_spell(p1, spell_obj)
    engine.rules.put_triggers_on_stack()
    assert len(engine.state.stack) == 2
    engine.rules.exile(prismari)  # the spell's trigger survives losing the grant
    response = spell("Response", "", "Instant", is_instant=True)
    engine.cast_spell(p1, response)
    engine.resolve_until_stable()
    # Exactly one copy for the preceding rock, not a second for the response.
    assert len(p1.hand) == 2 and len(p1.library) == 2


def test_printed_storm_also_copies_only_previous_casts_and_copies_are_not_cast():
    from mtg_analyzer.models.game.events import EventType

    engine, p1, p2 = _game()
    for name, text in [("First", ""), ("Storm Draw", "Storm\nDraw a card.")]:
        obj = GameObject(Card(id=name, name=name, type_line="Sorcery", is_sorcery=True, oracle_text=text,
                               keywords=["Storm"] if name == "Storm Draw" else []),
                         owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(obj)
        p1.hand.append(obj)
        engine.cast_spell(p1, obj)
        engine.resolve_until_stable()
    assert len(p1.hand) == 2
    assert sum(e.type == EventType.SPELL_CAST for e in engine.state.events_this_turn()) == 2


def test_stitch_together_returns_to_hand_but_to_the_battlefield_with_threshold():
    for fillers, expected in ((4, Zone.HAND), (6, Zone.BATTLEFIELD)):  # 5 cards vs 7 cards in the graveyard with the target
        engine, p1, p2 = _game("Stitch Together")
        target = _creature_card("Fallen Beast", "p1")
        p1.graveyard.append(target)
        _fill_graveyard(p1, fillers)
        p1.mana_pool.add_many({"B": 2})
        engine.cast_spell(p1, p1.hand[0], targets=[target])
        engine.resolve_until_stable()
        assert target.zone == expected, (fillers, target.zone)


def test_ghastly_demise_destroys_a_nonblack_creature_only_while_its_toughness_fits_my_graveyard():
    def cast(graveyard_cards, color):
        engine, p1, p2 = _game("Ghastly Demise")
        victim = battlefield_object(
            engine, "p2", "Victim", "Creature — Beast", is_creature=True, power=2, toughness=3, color_identity={color},
        )
        _fill_graveyard(p1, graveyard_cards)
        p1.mana_pool.add_many({"B": 1})
        engine.cast_spell(p1, p1.hand[0], targets=[victim])
        engine.resolve_until_stable()
        return victim

    assert cast(3, "G").zone != Zone.BATTLEFIELD  # toughness 3 <= 3 cards (+ the resolved spell makes 4 anyway)
    assert cast(1, "G").zone == Zone.BATTLEFIELD  # toughness 3 > 1 card in the graveyard: nothing happens


def test_agent_of_treachery_draws_three_at_my_end_step_with_three_permanents_i_dont_own():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    def end_step(foreign):
        engine, p1, p2 = _game()
        agent = GameObject(CardDatabase(DB_PATH).get_card("Agent of Treachery"), owner_id="p1", zone=Zone.BATTLEFIELD)
        agent.controller_id = "p1"
        bind_from_catalogue(agent)
        engine.state.add_to_battlefield(agent)
        for i in range(foreign):  # opponent-owned permanents under my control
            stolen = battlefield_object(engine, "p2", f"Stolen {i}", "Artifact")
            stolen.controller_id = "p1"
        for i in range(5):
            p1.library.append(GameObject(Card(id=f"X{i}", name=f"Extra {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
        before = len(p1.hand)
        engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", phase="ending", player_id="p1"))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()
        return len(p1.hand) - before

    assert end_step(2) == 0  # one short
    assert end_step(3) == 3


def test_liquimetal_torque_adds_the_artifact_type_until_end_of_turn_without_removing_others():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, p1, p2 = _game()
    torque = GameObject(CardDatabase(DB_PATH).get_card("Liquimetal Torque"), owner_id="p1", zone=Zone.BATTLEFIELD)
    torque.controller_id = "p1"
    bind_from_catalogue(torque)
    engine.state.add_to_battlefield(torque)
    torque.summoning_sick = False
    bear = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    land = battlefield_object(engine, "p2", "Their Land", "Land", is_land=True)

    pool = legal_targets(engine.state, "p1", TargetSpec(kind="nonland_permanent"), source=torque)
    assert land.name not in {o["name"] for o in pool} and bear.name in {o["name"] for o in pool}
    engine.activate_ability(p1, torque, 0, targets=[bear])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert "artifact" in bear.type_words  # an artifact ...
    assert bear.is_creature  # ... in addition to being a creature

    engine._step_cleanup()
    engine.recompute_continuous_effects()
    assert "artifact" not in bear.type_words and bear.is_creature


def test_phyrexian_furnace_exiles_the_bottom_card_of_a_players_graveyard():
    engine, p1, p2 = _game()
    furnace = GameObject(CardDatabase(DB_PATH).get_card("Phyrexian Furnace"), owner_id="p1", zone=Zone.BATTLEFIELD)
    furnace.controller_id = "p1"
    bind_from_catalogue(furnace)
    engine.state.add_to_battlefield(furnace)
    furnace.summoning_sick = False
    cards = []
    for name in ("Oldest", "Middle", "Newest"):  # appended in order: the last one is on top
        obj = GameObject(Card(id=name, name=name, type_line="Sorcery", is_sorcery=True), owner_id="p2", zone=Zone.GRAVEYARD)
        p2.graveyard.append(obj)
        cards.append(obj)
    engine.activate_ability(p1, furnace, 0, targets=[p2])
    engine.resolve_until_stable()
    assert cards[0].zone == Zone.EXILE and cards[1].zone == Zone.GRAVEYARD and cards[2].zone == Zone.GRAVEYARD


def test_marchesa_loots_two_cards_for_one_mana_when_i_commit_a_crime():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    marchesa = GameObject(CardDatabase(DB_PATH).get_card("Marchesa, Dealer of Death"), owner_id="p1", zone=Zone.BATTLEFIELD)
    marchesa.controller_id = "p1"
    bind_from_catalogue(marchesa)
    engine.state.add_to_battlefield(marchesa)
    p1.library.clear()
    cards = {}
    for name in ("Deep", "Second", "Top"):
        cards[name] = GameObject(Card(id=name, name=name, type_line="Land"), owner_id="p1", zone=Zone.LIBRARY)
        p1.library.append(cards[name])
    p1.mana_pool.add_many({"C": 1})

    engine.state.fire_event(GameEvent(EventType.CRIME_COMMITTED, player_id="p2", controller_id="p2"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and not engine.state.stack  # an opponent's crime does nothing

    engine.state.fire_event(GameEvent(EventType.CRIME_COMMITTED, player_id="p1", controller_id="p1"))
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "pay_cost_then"
    engine.resolve_pending_choice("pay")
    engine.resolve_until_stable()
    choice = engine.state.pending_choice
    assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"Top", "Second"}  # the top two cards
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == "Second"))
    engine.resolve_until_stable()
    assert cards["Second"] in p1.hand and cards["Top"] in p1.graveyard and cards["Deep"] in p1.library


def test_scholar_of_the_lost_trove_lets_me_cast_an_instant_sorcery_or_artifact_from_the_graveyard_for_free():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, p1, p2 = _game()
    scholar = GameObject(CardDatabase(DB_PATH).get_card("Scholar of the Lost Trove"), owner_id="p1", zone=Zone.BATTLEFIELD)
    scholar.controller_id = "p1"
    bind_from_catalogue(scholar)
    engine.state.add_to_battlefield(scholar)

    def grave(name, type_line, cost, **flags):
        obj = GameObject(
            Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=3, **flags),
            owner_id="p1", zone=Zone.GRAVEYARD,
        )
        p1.graveyard.append(obj)
        return obj

    spell = grave("Big Sorcery", "Sorcery", "{2}{R}", is_sorcery=True)
    rock = grave("Heavy Rock", "Artifact", "{3}")
    beast = grave("Beast", "Creature — Beast", "{2}{G}", is_creature=True, power=3, toughness=3)
    engine.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=scholar.instance_id, controller_id="p1", object_types=["creature"], player_id="p1",
    ))
    engine.rules.put_triggers_on_stack()
    choice = engine.state.pending_choice
    assert {o["label"] for o in choice["options"] if "instance_id" in o} == {"Big Sorcery", "Heavy Rock"}  # not the creature
    engine.resolve_pending_choice(next(o["id"] for o in choice["options"] if o.get("label") == "Heavy Rock"))
    engine.resolve_until_stable()

    assert rock.instance_id in engine.state.temp_flashback_grants and spell.instance_id not in engine.state.temp_flashback_grants
    assert engine.effective_cast_cost(p1, rock).converted_mana_cost == 0  # without paying its mana cost
    engine.cast_spell(p1, rock)  # an empty mana pool
    engine.resolve_until_stable()
    assert rock.zone == Zone.BATTLEFIELD and beast.zone == Zone.GRAVEYARD
