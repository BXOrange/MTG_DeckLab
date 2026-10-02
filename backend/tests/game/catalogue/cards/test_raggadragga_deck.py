"""Hand-authored cards of the saved "Raggadragga, Goreguts Boss" deck (PLAY-ALL Step 2)."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from tests.support.catalogue import battlefield_object, two_player_game


def test_wirewood_herald_fetches_an_elf_when_it_dies():
    engine, player = two_player_game()
    herald = battlefield_object(
        engine, "p1", "Wirewood Herald", "Creature — Elf", is_creature=True, power=1, toughness=1,
    )
    bind_from_catalogue(herald)
    elf = GameObject(Card(id="Elf", name="Llanowar Elf", type_line="Creature — Elf Druid", is_creature=True, power=1, toughness=1),
                     owner_id="p1", zone=Zone.LIBRARY)
    bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.LIBRARY)
    player.library.extend([bear, elf])

    engine.rules.destroy(herald)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    while engine.state.pending_choice:
        choice = engine.state.pending_choice
        options = [o for o in choice["options"] if o["id"] != "decline"]
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_until_stable()
    assert elf in player.hand and bear not in player.hand  # only Elf cards qualify


def test_akromas_memorial_grants_every_creature_you_control_the_full_set():
    engine, player = two_player_game()
    memorial = battlefield_object(engine, "p1", "Akroma's Memorial", "Legendary Artifact")
    bind_from_catalogue(memorial)
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()

    for keyword in ("flying", "first_strike", "vigilance", "trample", "haste"):
        assert keyword in mine.granted_keywords, keyword
        assert keyword not in theirs.granted_keywords, keyword

    # protection from black and from red (RULE 702.16), read colour off the source
    from mtg_analyzer.game import combat

    black = battlefield_object(engine, "p2", "Black Zombie", "Creature — Zombie", is_creature=True, power=2, toughness=2, color_identity={"B"})
    red = battlefield_object(engine, "p2", "Red Goblin", "Creature — Goblin", is_creature=True, power=2, toughness=2, color_identity={"R"})
    green = battlefield_object(engine, "p2", "Green Bear", "Creature — Bear", is_creature=True, power=2, toughness=2, color_identity={"G"})
    assert combat.is_protected_from(mine, black) and combat.is_protected_from(mine, red)
    assert not combat.is_protected_from(mine, green)
    assert not combat.is_protected_from(theirs, black)  # only my creatures


def test_saryth_grants_by_tapped_state_and_untaps_another_creature_or_land():
    engine, player = two_player_game()
    saryth = battlefield_object(
        engine, "p1", "Saryth, the Viper's Fang", "Legendary Creature — Human Warlock",
        is_creature=True, power=2, toughness=2,
    )
    bind_from_catalogue(saryth)
    saryth.summoning_sick = False
    tapped_bear = battlefield_object(engine, "p1", "Tapped Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    fresh_bear = battlefield_object(engine, "p1", "Fresh Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    forest = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    tapped_bear.tapped = True
    forest.tapped = True
    engine.recompute_continuous_effects()
    assert "deathtouch" in tapped_bear.granted_keywords and "hexproof" not in tapped_bear.granted_keywords
    assert "hexproof" in fresh_bear.granted_keywords and "deathtouch" not in fresh_bear.granted_keywords

    index = next(
        i for i, a in enumerate(saryth.activated_abilities)
        if any(getattr(e, "untap", False) for e in getattr(a, "effects", []))
    )
    player.mana_pool.add_many({"C": 1})
    engine.activate_ability(player, saryth, index, targets=[tapped_bear])
    engine.resolve_until_stable()
    assert not tapped_bear.tapped and saryth.tapped

    saryth.tapped = False
    player.mana_pool.add_many({"C": 1})
    engine.activate_ability(player, saryth, index, targets=[forest])
    engine.resolve_until_stable()
    assert not forest.tapped  # lands work too

    from mtg_analyzer.game import targeting
    assert saryth not in targeting.legal_targets(
        engine.state, player, targeting.TargetSpec(kind="another_creature_or_land_you_control"), source=saryth,
    )


def test_twitching_doll_taps_for_mana_with_a_nest_counter_then_sacrifices_for_spiders():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    card = CardDatabase(DB_PATH).get_card("Twitching Doll")
    doll = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    doll.controller_id = "p1"
    bind_from_catalogue(doll)
    doll.summoning_sick = False
    engine.state.add_to_battlefield(doll)
    engine.state.current_step = "main1"

    engine.tap_for_mana(player, doll)
    assert doll.counters.get("nest", 0) == 1  # the mana ability's own rider
    doll.counters["nest"] = 3
    doll.tapped = False

    index = next(i for i, a in enumerate(doll.activated_abilities) if getattr(a, "cost", None) is not None
                 and "sacrifice" in str(getattr(a.cost, "raw", getattr(a.cost, "text", a.cost))).lower())
    engine.activate_ability(player, doll, index)
    engine.resolve_until_stable()

    spiders = [o for o in engine.state.battlefield if "Spider" in (o.card.type_line or "")]
    assert doll not in engine.state.battlefield
    assert len(spiders) == 3  # one per nest counter
    assert all(s.power == 2 and s.toughness == 2 and "reach" in s.granted_keywords | set(getattr(s.card, "keywords", []) or []) for s in spiders)


def test_march_of_the_world_ooze_makes_my_creatures_6_6_oozes_and_rewards_off_turn_spells():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    engine, player = two_player_game()  # p1 is the active player
    march = battlefield_object(engine, "p1", "March of the World Ooze", "Enchantment")
    bind_from_catalogue(march)
    mine = battlefield_object(engine, "p1", "My Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    engine.recompute_continuous_effects()
    assert (mine.power, mine.toughness) == (6, 6) and (theirs.power, theirs.toughness) == (2, 2)
    from mtg_analyzer.game.continuous import has_subtype

    assert has_subtype(mine, "Ooze") and not has_subtype(theirs, "Ooze")

    def elephants():
        return [o for o in engine.state.permanents_controlled_by("p1") if "Elephant" in (o.card.type_line or "")]

    def opponent_casts():
        engine.state.fire_event(GameEvent(
            EventType.SPELL_CAST, player_id="p2", controller_id="p2", object="Bolt",
            object_types=["instant"], mana_value=1,
        ))
        engine.rules.put_triggers_on_stack()
        engine.resolve_until_stable()

    opponent_casts()  # during MY turn: it's not their turn -> an Elephant
    assert len(elephants()) == 1

    engine.state.active_player_index = 1  # their own turn: nothing
    opponent_casts()
    assert len(elephants()) == 1


def test_rishkar_gives_creatures_with_a_counter_a_green_mana_ability():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    engine, player = two_player_game()
    rishkar = battlefield_object(
        engine, "p1", "Rishkar, Peema Renegade", "Legendary Creature — Elf Druid", is_creature=True, power=2, toughness=2,
    )
    bind_from_catalogue(rishkar)
    countered = battlefield_object(engine, "p1", "Grown Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    plain = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    theirs = battlefield_object(engine, "p2", "Their Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    countered.counters["+1/+1"] = 1
    theirs.counters["+1/+1"] = 1
    for creature in (countered, plain, theirs):
        creature.summoning_sick = False
    engine.recompute_continuous_effects()

    assert mana_abilities_for(countered, engine.state)
    assert not mana_abilities_for(plain, engine.state)
    assert not mana_abilities_for(theirs, engine.state)  # only creatures I control

    engine.tap_for_mana(player, countered)
    assert player.mana_pool.pool.get("G", 0) == 1


def test_orochi_merge_keeper_taps_for_gg_only_while_modified():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    card = CardDatabase(DB_PATH).get_card("Orochi Merge-Keeper")
    keeper = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    keeper.controller_id = "p1"
    bind_from_catalogue(keeper)
    keeper.summoning_sick = False
    engine.state.add_to_battlefield(keeper)
    engine.recompute_continuous_effects()

    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    def best_amount():
        return max(sum(opt.values()) for ability in mana_abilities_for(keeper, engine.state) for opt in ability.options)

    assert best_amount() == 1  # unmodified: just the printed {T}: Add {G}
    keeper.counters["+1/+1"] = 1  # a counter is a modification
    engine.recompute_continuous_effects()
    assert best_amount() == 2


def test_freyalise_plus_two_makes_a_mana_elf_and_minus_six_draws_per_green_creature():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    engine, player = two_player_game()
    card = CardDatabase(DB_PATH).get_card("Freyalise, Llanowar's Fury")
    freyalise = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    freyalise.controller_id = "p1"
    bind_from_catalogue(freyalise)
    engine.state.add_to_battlefield(freyalise)
    engine.state.current_step = "main1"
    freyalise.counters["loyalty"] = 3

    def ability_with_loyalty(amount):
        return next(
            i for i, a in enumerate(freyalise.activated_abilities)
            if getattr(getattr(a, "cost", None), "loyalty", None) == amount
        )

    engine.activate_ability(player, freyalise, ability_with_loyalty(2))
    engine.resolve_until_stable()
    elves = [o for o in engine.state.permanents_controlled_by("p1") if "Elf" in (o.card.type_line or "") and o.is_creature]
    assert len(elves) == 1 and freyalise.counters["loyalty"] == 5

    elf = elves[0]
    elf.summoning_sick = False
    engine.tap_for_mana(player, elf)
    assert player.mana_pool.pool.get("G", 0) == 1  # the token's quoted mana ability

    # -6: one card per green creature I control (the Elf token is green)
    freyalise.counters["loyalty"] = 6
    freyalise.activated_loyalty_this_turn = False  # RULE 606.3: one loyalty ability per turn
    for i in range(3):
        player.library.append(GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line="Land"), owner_id="p1", zone=Zone.LIBRARY))
    hand_before = len(player.hand)
    engine.activate_ability(player, freyalise, ability_with_loyalty(-6))
    engine.resolve_until_stable()
    assert len(player.hand) == hand_before + 1


def test_last_march_of_the_ents_draws_greatest_toughness_then_puts_creatures_in():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.game.game_engine import GameEngine
    from mtg_analyzer.services.card_database import CardDatabase

    card = CardDatabase(DB_PATH).get_card("Last March of the Ents")
    engine = GameEngine.new_game([("p1", "A", [card]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in engine.state.players[0].hand:
        bind_from_catalogue(obj)
    engine.begin_turn()
    engine.state.current_step = "main1"
    p1 = engine.state.player_by_id("p1")
    battlefield_object(engine, "p1", "Wall", "Creature — Wall", is_creature=True, power=0, toughness=4)
    battlefield_object(engine, "p1", "Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    battlefield_object(engine, "p2", "Their Titan", "Creature — Giant", is_creature=True, power=9, toughness=9)
    engine.recompute_continuous_effects()

    def lib(i, type_line, **kw):
        return GameObject(Card(id=f"L{i}", name=f"Lib {i}", type_line=type_line, **kw), owner_id="p1", zone=Zone.LIBRARY)

    for i in range(3):
        p1.library.append(lib(i, "Creature — Elf", is_creature=True, power=1, toughness=1))
    p1.library.append(lib(3, "Land"))
    p1.library.append(lib(4, "Land"))
    p1.mana_pool.add_many({"G": 5, "C": 3})

    engine.cast_spell(p1, next(o for o in p1.hand if o.name == "Last March of the Ents"))
    engine.resolve_until_stable()
    # greatest toughness among MY creatures is 4 (their 9 does not count): 4 cards drawn
    assert sum(1 for o in p1.hand if o.name.startswith("Lib")) == 4
    picks = 0
    while engine.state.pending_choice and picks < 10:
        options = [o for o in engine.state.pending_choice["options"] if o["id"] != "decline"]
        if not options:
            break
        engine.resolve_pending_choice(options[0]["id"])
        engine.resolve_until_stable()
        picks += 1
    on_board_elves = [o for o in engine.state.battlefield if "Elf" in (o.card.type_line or "")]
    # the library is drawn from its end: Lib 4 (land), 3 (land), 2 and 1 (Elves) come into hand
    assert sorted(o.name for o in on_board_elves) == ["Lib 1", "Lib 2"]  # every drawn creature card, one pick each
    assert not [o for o in p1.hand if "Elf" in (o.card.type_line or "")]
    assert sorted(o.name for o in p1.hand) == ["Lib 3", "Lib 4"]  # the drawn lands stay in hand


def test_raggadragga_buffs_and_untaps_attackers_with_a_mana_ability():
    engine, player = two_player_game()
    boss = battlefield_object(
        engine, "p1", "Raggadragga, Goreguts Boss", "Legendary Creature — Troll Shaman",
        is_creature=True, power=2, toughness=2,
    )
    bind_from_catalogue(boss)
    # a Llanowar-style creature: its mana ability is printed in its own text
    elf = battlefield_object(
        engine, "p1", "Llanowar Elves", "Creature — Elf Druid", is_creature=True, power=1, toughness=1,
        oracle_text="{T}: Add {G}.",
    )
    bear = battlefield_object(engine, "p1", "Plain Bear", "Creature — Bear", is_creature=True, power=2, toughness=2)
    for creature in (boss, elf, bear):
        creature.summoning_sick = False
    engine.recompute_continuous_effects()

    assert (elf.power, elf.toughness) == (3, 3)  # 1/1 +2/+2: it has a mana ability
    assert (bear.power, bear.toughness) == (2, 2)  # no mana ability: untouched
    assert (boss.power, boss.toughness) == (2, 2)  # Raggadragga has none itself

    engine.state.current_step = "declare_attackers"
    engine.declare_attackers(player, [elf, bear])
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert not elf.tapped  # untapped by the trigger (it attacked, so it was tapped)
    assert bear.tapped  # no mana ability: stays tapped from attacking
